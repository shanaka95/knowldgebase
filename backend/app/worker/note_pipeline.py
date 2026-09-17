"""Indexing one note.

Deliberately not `run_job`. That pipeline chunks with an LLM and writes a
summary with another, which is right for a page somebody will read a year from
now and absurd for a two-line shopping list: two chat calls and tens of seconds
of latency to index eleven words.

So this one embeds, and stops. Title plus text as a single `document` point;
for a long note, plain-Python paragraph chunks as well. No LLM call anywhere,
no summary, and therefore no `summary` kind in the note corpus - which is
honest, because nothing wrote one.

The result is that a note is searchable a few seconds after it is saved rather
than a minute, and that indexing one costs a single embedding call.
"""

from __future__ import annotations

import asyncio

from app.core.content import html_to_blocks
from app.models import (
    EmbeddingKind,
    EmbeddingStatus,
    JobStage,
    JobStatus,
    NoteEmbeddingJob,
)
from app.services.embeddings import EmbeddingDimensionError
from app.services.sparse import encode_document
from app.services.vectors import Point, build_note_payload, note_point_id
from app.worker import queue
from app.worker.context import NoteJobContext
from app.worker.errors import FatalError, JobCancelled, JobSuperseded
from app.worker.fallback_chunker import Chunk, fallback_chunk
from app.worker.pipeline import PipelineDeps

# Below this a note is one point and nothing else. Splitting a paragraph into
# "chunks" would file the same words twice and let a short note outrank a long
# one purely by being counted more often.
CHUNK_FROM_CHARS = 1200


def build_note_points(
    *,
    note: queue.NoteSnapshot,
    doc_version: int,
    vectors: list[list[float]],
    texts: list[str],
    chunks: list[Chunk],
) -> list[Point]:
    """The whole-note point first, then one per chunk, in the order embedded."""
    points: list[Point] = []
    kinds: list[tuple[EmbeddingKind, int, str, int | None]] = [
        (EmbeddingKind.document, 0, note.title, None)
    ]
    for index, chunk in enumerate(chunks):
        kinds.append((EmbeddingKind.chunk, index, chunk.title or note.title, index))

    for (kind, index, title, chunk_index), vector, text in zip(
        kinds, vectors, texts, strict=False
    ):
        points.append(
            Point(
                id=note_point_id(note.id, doc_version, str(kind), index),
                vector=vector,
                payload=build_note_payload(
                    note_id=note.id,
                    owner_id=note.user_id,
                    namespace_id=note.namespace_id,
                    kind=kind,
                    doc_version=doc_version,
                    title=title,
                    chunk_index=chunk_index,
                    char_count=len(text),
                ),
                sparse=encode_document(text),
            )
        )
    return points


async def run_note_job(job: NoteEmbeddingJob, deps: PipelineDeps) -> JobStatus:
    owner = await asyncio.to_thread(queue.note_owner, job.note_id)
    ctx = NoteJobContext(job, user_id=owner)

    try:
        if owner is not None and not await asyncio.to_thread(queue.has_credit, owner):
            raise FatalError("no credit")

        await ctx.set_stage(JobStage.loading, 5, EmbeddingStatus.embedding)
        note = await asyncio.to_thread(queue.load_note, job.note_id)
        if note is None:
            raise JobSuperseded("note deleted")
        if note.version != job.doc_version:
            raise JobSuperseded(
                f"note at v{note.version}, job wants v{job.doc_version}"
            )

        body = note.content_text.strip()
        whole = "\n\n".join(part for part in (note.title.strip(), body) if part)
        if not whole:
            # An empty note is a real state - somebody opened one and has not
            # written yet. Nothing to embed, and marking it ready stops the
            # self-healing sweep from picking it up on every tick for ever.
            await asyncio.to_thread(
                queue.commit_note_results,
                job_id=job.id,
                note_id=note.id,
                doc_version=job.doc_version,
                chunks=[],
                stats=ctx.finalize_stats(),
            )
            return JobStatus.succeeded

        chunks: list[Chunk] = []
        if len(body) >= CHUNK_FROM_CHARS:
            blocks = html_to_blocks(f"<p>{body}</p>") if body else []
            chunks, _ = fallback_chunk(blocks)

        await ctx.checkpoint()
        await ctx.set_stage(JobStage.embedding, 40, EmbeddingStatus.embedding)

        texts = [whole] + [f"{c.title}\n\n{c.text}".strip() for c in chunks]
        vectors = await deps.embedder.embed(texts, meter=ctx.meter)

        await ctx.checkpoint()
        await ctx.set_stage(JobStage.writing, 85, EmbeddingStatus.embedding)

        points = build_note_points(
            note=note,
            doc_version=job.doc_version,
            vectors=vectors,
            texts=texts,
            chunks=chunks,
        )
        await deps.vectors.upsert(points)
        await deps.vectors.delete_older_note_versions(
            note.id, keep_version=job.doc_version
        )

        await asyncio.to_thread(
            queue.commit_note_results,
            job_id=job.id,
            note_id=note.id,
            doc_version=job.doc_version,
            chunks=chunks,
            stats=ctx.finalize_stats(),
        )
        return JobStatus.succeeded

    except JobSuperseded as exc:
        await asyncio.to_thread(
            queue.finish_note_job, job.id, JobStatus.superseded, str(exc)
        )
        return JobStatus.superseded
    except JobCancelled:
        await asyncio.to_thread(queue.finish_note_job, job.id, JobStatus.cancelled)
        return JobStatus.cancelled
    except asyncio.CancelledError:
        # Shutting down: hand the job back so another worker takes it. Otherwise
        # this was a real cancellation and the job is done with.
        if deps.shutting_down():
            await asyncio.to_thread(queue.release_note_job, job.id)
            return JobStatus.queued
        await asyncio.to_thread(queue.finish_note_job, job.id, JobStatus.cancelled)
        return JobStatus.cancelled
    except (EmbeddingDimensionError, FatalError) as exc:
        return await asyncio.to_thread(
            queue.retry_or_fail_note,
            job.id,
            str(exc),
            ctx.finalize_stats(),
            force_fail=True,
        )
    except Exception as exc:  # noqa: BLE001
        return await asyncio.to_thread(
            queue.retry_or_fail_note, job.id, str(exc), ctx.finalize_stats()
        )
    finally:
        await asyncio.to_thread(ctx.meter.flush)
