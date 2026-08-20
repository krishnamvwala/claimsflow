"""Generation-pinned Google Cloud Storage landing adapter."""

from __future__ import annotations

import hashlib
import re
import tempfile
from importlib import import_module
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Protocol, cast

from claimsflow.domain.cloud import LandingObjectReceipt, LandingObjectRequest

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LandingStorageError(RuntimeError):
    """Raised when immutable landing evidence cannot be published or verified."""


class _Blob(Protocol):
    generation: int | None
    size: int | None
    metadata: dict[str, str] | None

    def upload_from_filename(
        self,
        filename: str,
        *,
        content_type: str,
        if_generation_match: int,
        checksum: str,
    ) -> None: ...

    def reload(self, *, if_generation_match: int | None = None) -> None: ...

    def download_to_file(
        self,
        file_obj: BinaryIO,
        *,
        if_generation_match: int,
        checksum: str,
    ) -> None: ...


class _Bucket(Protocol):
    def blob(self, blob_name: str, generation: int | None = None) -> _Blob: ...


class _StorageClient(Protocol):
    def bucket(self, bucket_name: str) -> _Bucket: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_object_name(value: str) -> str:
    if not value or "\\" in value or any(ord(character) < 32 for character in value):
        raise LandingStorageError("landing object name contains unsafe characters")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise LandingStorageError("landing object name must be a safe relative path")
    canonical = path.as_posix()
    if canonical != value:
        raise LandingStorageError("landing object name must use one canonical path spelling")
    return canonical


class GoogleCloudStorageLandingAdapter:
    """Create-only GCS object publisher with generation and checksum verification."""

    def __init__(
        self,
        client: _StorageClient,
        bucket_name: str,
        *,
        precondition_error_types: tuple[type[BaseException], ...] = (),
    ) -> None:
        if not bucket_name or "/" in bucket_name:
            raise ValueError("bucket_name must be one Google Cloud Storage bucket")
        self._client = client
        self.bucket_name = bucket_name
        self._precondition_error_types = precondition_error_types

    @classmethod
    def from_default_credentials(
        cls,
        bucket_name: str,
        *,
        project: str | None = None,
    ) -> GoogleCloudStorageLandingAdapter:
        """Compose the adapter with Application Default Credentials only when requested."""

        exceptions = import_module("google.api_core.exceptions")
        storage = import_module("google.cloud.storage")
        precondition_failed = cast(type[BaseException], exceptions.PreconditionFailed)
        client = cast(_StorageClient, storage.Client(project=project))
        return cls(
            client,
            bucket_name,
            precondition_error_types=(precondition_failed,),
        )

    def _validate_request(self, request: LandingObjectRequest) -> str:
        object_name = _safe_object_name(request.object_name)
        if request.metadata.get("synthetic_only") != "true":
            raise LandingStorageError("landing upload requires synthetic_only=true metadata")
        if not _SHA256.fullmatch(request.checksum_sha256):
            raise LandingStorageError("landing checksum must be lowercase SHA-256")
        path = request.source_path
        if path.is_symlink() or not path.is_file():
            raise LandingStorageError(f"landing source is missing or unsafe: {path}")
        if path.stat().st_size != request.byte_size:
            raise LandingStorageError("landing source byte size changed before upload")
        if _sha256(path) != request.checksum_sha256:
            raise LandingStorageError("landing source checksum changed before upload")
        if not request.content_type.strip():
            raise LandingStorageError("landing content type cannot be blank")
        if any(
            not isinstance(key, str) or not key or not isinstance(value, str) or not value
            for key, value in request.metadata.items()
        ):
            raise LandingStorageError("landing metadata must contain non-empty strings")
        return object_name

    def _receipt(
        self,
        blob: _Blob,
        request: LandingObjectRequest,
        *,
        reload_without_generation: bool,
    ) -> LandingObjectReceipt:
        if reload_without_generation:
            blob.reload()
        if blob.generation is None:
            blob.reload()
        generation = blob.generation
        if generation is None:
            raise LandingStorageError("landing object has no generation evidence")
        generation = int(generation)
        blob.reload(if_generation_match=generation)
        if blob.size is None or int(blob.size) != request.byte_size:
            raise LandingStorageError("landing object byte size does not match source evidence")
        metadata = blob.metadata or {}
        for key, value in request.metadata.items():
            if metadata.get(key) != value:
                raise LandingStorageError(f"landing object metadata mismatch for {key}")
        if metadata.get("checksum_sha256") != request.checksum_sha256:
            raise LandingStorageError("landing object checksum metadata does not match")
        return LandingObjectReceipt(
            bucket=self.bucket_name,
            object_name=request.object_name,
            generation=generation,
            checksum_sha256=request.checksum_sha256,
            byte_size=request.byte_size,
        )

    def upload(self, request: LandingObjectRequest) -> LandingObjectReceipt:
        """Create an immutable object or prove the existing live object is identical."""

        object_name = self._validate_request(request)
        bucket = self._client.bucket(self.bucket_name)
        blob = bucket.blob(object_name)
        blob.metadata = {**request.metadata, "checksum_sha256": request.checksum_sha256}
        try:
            blob.upload_from_filename(
                str(request.source_path),
                content_type=request.content_type,
                if_generation_match=0,
                checksum="auto",
            )
        except self._precondition_error_types:
            existing = bucket.blob(object_name)
            receipt = self._receipt(
                existing,
                request,
                reload_without_generation=True,
            )
            self.verify(receipt)
            return receipt
        return self._receipt(blob, request, reload_without_generation=False)

    def verify(self, receipt: LandingObjectReceipt) -> None:
        """Download and hash the exact generation before downstream raw loading."""

        if receipt.bucket != self.bucket_name:
            raise LandingStorageError("landing receipt belongs to a different bucket")
        _safe_object_name(receipt.object_name)
        if receipt.generation <= 0:
            raise LandingStorageError("landing receipt generation must be positive")
        if not _SHA256.fullmatch(receipt.checksum_sha256):
            raise LandingStorageError("landing receipt checksum must be lowercase SHA-256")

        blob = self._client.bucket(self.bucket_name).blob(
            receipt.object_name,
            generation=receipt.generation,
        )
        try:
            blob.reload(if_generation_match=receipt.generation)
            if blob.generation is None or int(blob.generation) != receipt.generation:
                raise LandingStorageError("landing object generation changed")
            if blob.size is None or int(blob.size) != receipt.byte_size:
                raise LandingStorageError("landing object byte size changed")
            metadata = blob.metadata or {}
            if metadata.get("synthetic_only") != "true":
                raise LandingStorageError("landing object lost synthetic-only evidence")
            if metadata.get("checksum_sha256") != receipt.checksum_sha256:
                raise LandingStorageError("landing object checksum metadata changed")
            with tempfile.TemporaryFile(mode="w+b") as downloaded:
                blob.download_to_file(
                    downloaded,
                    if_generation_match=receipt.generation,
                    checksum="auto",
                )
                downloaded.seek(0)
                digest = hashlib.sha256()
                byte_size = 0
                for block in iter(lambda: downloaded.read(1024 * 1024), b""):
                    byte_size += len(block)
                    digest.update(block)
        except self._precondition_error_types as error:
            raise LandingStorageError(
                "landing object generation changed during verification"
            ) from error

        if byte_size != receipt.byte_size or digest.hexdigest() != receipt.checksum_sha256:
            raise LandingStorageError("landing object content checksum verification failed")
