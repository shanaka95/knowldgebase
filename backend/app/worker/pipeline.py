"""The embedding pipeline for one job.

Stages (each reported to the document row for live UI):

    loading → chunking → summarizing → embedding → writing → done

Cancellation: the runner cancels the asyncio task when the job row asks for it
(newer document version, manual regenerate, deletion). In addition
``ctx.checkpoint()`` re-reads the flags at every stage boundary, and the final
write re-checks the document version under a row lock.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.content import blocks_to_text, html_to_blocks
from app.models import (
    ChunkingMethod,
    EmbeddingJob,
    EmbeddingKind,
    EmbeddingStatus,
    JobStage,
    JobStatus,
)
from app.services.embeddings import EmbeddingClient, EmbeddingDimensionError
from app.services.llm import LLMClient
from app.services.sparse import encode_document
from app.services.vectors import Point, VectorStore, build_payload, point_id
from app.worker import queue
from app.worker.chunking import semantic_chunk
from app.worker.context import JobContext
from app.worker.errors import FatalError, JobCancelled, JobSuperseded
from app.worker.fallback_chunker import Chunk
from app.worker.summarize import summarize

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineDeps:
    llm: LLMClient
    embedder: EmbeddingClient
    vectors: VectorStore
    shutting_down: Callable[[], bool] = field(default=lambda: False)


def build_points(
    *,
    doc: queue.DocumentSnapshot,
    doc_version: int,
    vectors: list[list[float]],
    texts: list[str],
    summary: str | None,
    chunks: list[Chunk],
) -> list[Point]:
    """Build one Qdrant point per embedded text.

    ``texts`` is the same list that was embedded, in the same order, so each
    point gets both its dense vector and the BM25 sparse vector of that text.
    """
    points: list[Point] = []
    cursor = 0
    points.append(
        Point(
            id=point_id(doc.id, doc_version, EmbeddingKind.document, 0),
            vector=vectors[cursor],
            sparse=encode_document(texts[cursor]),
            payload=build_payload(
                document_id=doc.id,
                namespace_id=doc.namespace_id,
                kind=EmbeddingKind.document,
                doc_version=doc_version,
                title=doc.title,
            ),
        )
    )
    cursor += 1
    if summary:
        points.append(
            Point(
                id=point_id(doc.id, doc_version, EmbeddingKind.summary, 0),
                vector=vectors[cursor],
                sparse=encode_document(texts[cursor]),
                payload=build_payload(
                    document_id=doc.id,
                    namespace_id=doc.namespace_id,
                    kind=EmbeddingKind.summary,
                    doc_version=doc_version,
                    title=doc.title,
                    char_count=len(summary),
                ),
            )
        )
        cursor += 1
    for index, chunk in enumerate(chunks):
        points.append(
            Point(
                id=point_id(doc.id, doc_version, EmbeddingKind.chunk, index),
                vector=vectors[cursor],
                sparse=encode_document(texts[cursor]),
                payload=build_payload(
                    document_id=doc.id,
                    namespace_id=doc.namespace_id,
                    kind=EmbeddingKind.chunk,
                    doc_version=doc_version,
                    title=chunk.title,
                    chunk_index=index,
                    char_count=chunk.char_count,
                ),
            )
        )
        cursor += 1
    return points


async def _embed_all(
    embedder: EmbeddingClient, inputs: list[str], ctx: JobContext
) -> list[list[float]]:
    vectors: list[list[float]] = []
    batch_size = embedder.batch_size
    total = len(inputs)
    for start in range(0, total, batch_size):
        await ctx.checkpoint()  # [CK] before every embedding batch
        vectors.extend(await embedder.embed_batch(inputs[start : start + batch_size]))
        done = min(start + batch_size, total)
        await ctx.set_progress(60 + int(30 * done / max(total, 1)))
    return vectors


async def run_job(job: EmbeddingJob, deps: PipelineDeps) -> JobStatus:
    """Run one claimed job to a terminal state. Never raises except on shutdown."""
    ctx = JobContext(job)
    log = logging.LoggerAdapter(
        logger, {"job": str(job.id)[:8], "doc": str(job.document_id)[:8]}
    )
    try:
        await ctx.set_stage(JobStage.loading, 5)
        doc = await asyncio.to_thread(queue.load_document, job.document_id)
        if doc is None:
            await asyncio.to_thread(
                queue.finish_job, job.id, JobStatus.cancelled, "document deleted"
            )
            return JobStatus.cancelled
        if doc.version != job.doc_version:
            raise JobSuperseded()
        await ctx.checkpoint()  # [CK1]

        blocks = html_to_blocks(doc.content_html)
        body_text = blocks_to_text(blocks)
        full_text = f"{doc.title}\n\n{body_text}".strip()
        ctx.stats["chars"] = len(body_text)
        ctx.stats["blocks"] = len(blocks)

        # --- chunking -------------------------------------------------------
        await ctx.set_stage(JobStage.chunking, 10, EmbeddingStatus.chunking)
        chunks: list[Chunk] = []
        method = ChunkingMethod.none_short
        if len(body_text) >= settings.LLM_MIN_CHARS_FOR_CHUNKING:
            result = await semantic_chunk(
                deps.llm,
                doc.title,
                blocks,
                checkpoint=ctx.checkpoint,  # [CK2] per LLM call
            )
            chunks, method = result.chunks, result.method
            ctx.stats.update(result.stats)
        await ctx.checkpoint()  # [CK3]

        # --- summary ----------------------------------------------------------
        await ctx.set_stage(JobStage.summarizing, 40, EmbeddingStatus.summarizing)
        summary = await summarize(
            deps.llm,
            doc.title,
            blocks,
            checkpoint=ctx.checkpoint,  # [CK4]
        )
        await ctx.checkpoint()  # [CK5]

        # --- embeddings -----------------------------------------------------
        await ctx.set_stage(JobStage.embedding, 60, EmbeddingStatus.embedding)
        inputs = [full_text]
        if summary:
            inputs.append(summary)
        inputs.extend(f"{c.title}\n\n{c.text}" for c in chunks)
        vectors = await _embed_all(deps.embedder, inputs, ctx)  # [CK6] per batch

        # --- write ------------------------------------------------------------
        await ctx.set_stage(JobStage.writing, 90)
        await ctx.checkpoint()  # [CK7] final gate before touching the vector store
        points = build_points(
            doc=doc,
            doc_version=job.doc_version,
            vectors=vectors,
            texts=inputs,
            summary=summary,
            chunks=chunks,
        )
        await deps.vectors.upsert(points)  # idempotent ids → safe to repeat
        await deps.vectors.delete_older_versions(doc.id, keep_version=job.doc_version)
        ctx.stats["points"] = len(points)
        ctx.stats["chunks"] = len(chunks)
        await asyncio.to_thread(
            queue.commit_results,
            job_id=job.id,
            document_id=doc.id,
            doc_version=job.doc_version,
            summary=summary,
            chunks=chunks,
            chunking_method=str(method),
            stats=ctx.finalize_stats(),
        )
        log.info(
            "embedded v%s: %s chunks (%s), %s points",
            job.doc_version,
            len(chunks),
            method,
            len(points),
        )
        return JobStatus.succeeded

    except JobSuperseded:
        log.info("superseded by a newer document version")
        await asyncio.to_thread(
            queue.finish_job,
            job.id,
            JobStatus.superseded,
            "superseded by newer version",
            ctx.finalize_stats(),
        )
        return JobStatus.superseded
    except JobCancelled:
        log.info("cancelled (checkpoint)")
        await asyncio.to_thread(
            queue.finish_job,
            job.id,
            JobStatus.cancelled,
            "cancelled",
            ctx.finalize_stats(),
        )
        return JobStatus.cancelled
    except asyncio.CancelledError:
        if deps.shutting_down():
            log.info("released back to queue (worker shutting down)")
            await asyncio.shield(asyncio.to_thread(queue.release_job, job.id))
            raise
        log.info("cancelled (task)")
        await asyncio.shield(
            asyncio.to_thread(
                queue.finish_job,
                job.id,
                JobStatus.cancelled,
                "cancelled: superseded by a newer version",
                ctx.finalize_stats(),
            )
        )
        return JobStatus.cancelled
    except (EmbeddingDimensionError, FatalError) as exc:
        log.error("fatal: %s", exc)
        await asyncio.to_thread(
            queue.retry_or_fail, job.id, str(exc), ctx.finalize_stats(), force_fail=True
        )
        return JobStatus.failed
    except Exception as exc:  # noqa: BLE001
        log.warning("failed: %s", exc, exc_info=True)
        status = await asyncio.to_thread(
            queue.retry_or_fail,
            job.id,
            f"{type(exc).__name__}: {exc}",
            ctx.finalize_stats(),
        )
        return status
