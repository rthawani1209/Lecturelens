"""Blob storage for videos, audio and thumbnails.

LocalStorage is for tests and single-machine dev. S3Storage talks to MinIO locally
and to Google Cloud Storage in production (GCS speaks the S3 XML API with HMAC keys).
"""

import shutil
from pathlib import Path
from typing import Protocol

from .config import get_settings


class Storage(Protocol):
    def put_file(self, key: str, src: Path) -> None: ...
    def get_file(self, key: str, dst: Path) -> Path: ...
    def exists(self, key: str) -> bool: ...
    def delete_prefix(self, prefix: str) -> None: ...


def _safe_key(key: str) -> str:
    if key.startswith("/") or ".." in key.split("/"):
        raise ValueError(f"bad storage key: {key!r}")
    return key


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    def put_file(self, key: str, src: Path) -> None:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    def get_file(self, key: str, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._path(key), dst)
        return dst

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete_prefix(self, prefix: str) -> None:
        p = self._path(prefix)
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()


class S3Storage:
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str):
        import boto3

        self.bucket = bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )

    def put_file(self, key: str, src: Path) -> None:
        self.s3.upload_file(str(src), self.bucket, _safe_key(key))

    def get_file(self, key: str, dst: Path) -> Path:
        dst.parent.mkdir(parents=True, exist_ok=True)
        self.s3.download_file(self.bucket, _safe_key(key), str(dst))
        return dst

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.s3.head_object(Bucket=self.bucket, Key=_safe_key(key))
            return True
        except ClientError:
            return False

    def delete_prefix(self, prefix: str) -> None:
        pages = self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=_safe_key(prefix)
        )
        for page in pages:
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": objs})


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        if s.storage_backend == "local":
            _storage = LocalStorage(Path(s.local_storage_dir))
        else:
            _storage = S3Storage(s.s3_endpoint, s.s3_bucket, s.s3_access_key, s.s3_secret_key)
    return _storage


def set_storage(storage: Storage | None) -> None:
    """Tests swap in a LocalStorage on a temp dir."""
    global _storage
    _storage = storage
