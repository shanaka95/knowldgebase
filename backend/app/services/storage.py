"""Object storage abstraction (MinIO in production, in-memory in tests)."""

from __future__ import annotations

import io
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from app.core.config import settings


@dataclass(slots=True)
class StoredObject:
    stream: Iterator[bytes]
    size: int
    content_type: str
    close: Callable[[], None]


class ObjectStorage(Protocol):
    def ensure_bucket(self) -> None: ...
    def put(self, key: str, data: BinaryIO, size: int, content_type: str) -> None: ...
    def open(self, key: str) -> StoredObject: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def health(self) -> tuple[bool, float, str | None]: ...


class MinioStorage:
    def __init__(
        self,
        endpoint: str = settings.MINIO_ENDPOINT,
        access_key: str = settings.MINIO_ACCESS_KEY,
        secret_key: str = settings.MINIO_SECRET_KEY,
        bucket: str = settings.MINIO_BUCKET,
        secure: bool = settings.MINIO_SECURE,
    ) -> None:
        from minio import Minio

        self.bucket = bucket
        self.client = Minio(
            endpoint, access_key=access_key, secret_key=secret_key, secure=secure
        )

    def ensure_bucket(self) -> None:
        from minio.error import S3Error

        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error as exc:  # raced with another process
            if exc.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise

    def put(self, key: str, data: BinaryIO, size: int, content_type: str) -> None:
        self.client.put_object(
            self.bucket, key, data, length=size, content_type=content_type
        )

    def open(self, key: str) -> StoredObject:
        response = self.client.get_object(self.bucket, key)
        size = int(response.headers.get("Content-Length") or 0)
        content_type = (
            response.headers.get("Content-Type") or "application/octet-stream"
        )

        def close() -> None:
            response.close()
            response.release_conn()

        return StoredObject(
            stream=response.stream(64 * 1024),
            size=size,
            content_type=content_type,
            close=close,
        )

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def exists(self, key: str) -> bool:
        from minio.error import S3Error

        try:
            self.client.stat_object(self.bucket, key)
            return True
        except S3Error:
            return False

    def health(self) -> tuple[bool, float, str | None]:
        start = time.perf_counter()
        try:
            ok = self.client.bucket_exists(self.bucket)
            return (
                ok,
                (time.perf_counter() - start) * 1000,
                None if ok else "bucket missing",
            )
        except Exception as exc:  # noqa: BLE001
            return False, (time.perf_counter() - start) * 1000, str(exc)[:200]


class InMemoryStorage:
    """Dict-backed storage for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def ensure_bucket(self) -> None:
        return None

    def put(self, key: str, data: BinaryIO, size: int, content_type: str) -> None:
        self.objects[key] = (data.read(size), content_type)

    def open(self, key: str) -> StoredObject:
        payload, content_type = self.objects[key]
        buf = io.BytesIO(payload)

        def gen() -> Iterator[bytes]:
            while chunk := buf.read(64 * 1024):
                yield chunk

        return StoredObject(
            stream=gen(),
            size=len(payload),
            content_type=content_type,
            close=lambda: None,
        )

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.objects

    def health(self) -> tuple[bool, float, str | None]:
        return True, 0.0, None
