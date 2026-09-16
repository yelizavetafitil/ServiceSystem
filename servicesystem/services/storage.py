"""Storage backend abstraction (local FS or S3-compatible object storage)."""
import os
from abc import ABC, abstractmethod

from flask import current_app


class StorageBackend(ABC):
    @abstractmethod
    def ensure_dir(self, *parts: str) -> str: ...

    @abstractmethod
    def write(self, rel_path: str, data: bytes, offset: int = 0) -> None: ...

    @abstractmethod
    def read_path(self, rel_path: str) -> str:
        """Return filesystem path for send_file (local) or temp path."""

    @abstractmethod
    def exists(self, rel_path: str) -> bool: ...

    @abstractmethod
    def save_file(self, rel_path: str, file_obj) -> int: ...

    @abstractmethod
    def size(self, rel_path: str) -> int: ...


class LocalStorageBackend(StorageBackend):
    def __init__(self, base_path: str):
        self.base_path = base_path

    def _full(self, rel_path: str) -> str:
        return os.path.join(self.base_path, rel_path.replace("/", os.sep))

    def ensure_dir(self, *parts: str) -> str:
        path = os.path.join(self.base_path, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    def write(self, rel_path: str, data: bytes, offset: int = 0) -> None:
        path = self._full(rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "r+b" if offset and os.path.exists(path) else "wb") as f:
            if offset:
                f.seek(offset)
            f.write(data)

    def read_path(self, rel_path: str) -> str:
        return self._full(rel_path)

    def exists(self, rel_path: str) -> bool:
        return os.path.isfile(self._full(rel_path))

    def save_file(self, rel_path: str, file_obj) -> int:
        path = self._full(rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        file_obj.save(path)
        return os.path.getsize(path)

    def size(self, rel_path: str) -> int:
        return os.path.getsize(self._full(rel_path))


class S3StorageBackend(StorageBackend):
    """S3-compatible object storage (MinIO, AWS S3)."""

    def __init__(self, bucket: str, prefix: str = "", endpoint: str | None = None,
                 access_key: str | None = None, secret_key: str | None = None):
        import boto3
        from botocore.config import Config as BotoConfig

        kwargs = {"config": BotoConfig(signature_version="s3v4")}
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        if access_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        self.client = boto3.client("s3", **kwargs)
        self.bucket = bucket
        self.prefix = prefix.rstrip("/")
        self._cache_dir = os.path.join(os.environ.get("UPLOAD_FOLDER", "/tmp"), ".s3cache")
        os.makedirs(self._cache_dir, exist_ok=True)

    def _key(self, rel_path: str) -> str:
        rel = rel_path.replace("\\", "/").lstrip("/")
        return f"{self.prefix}/{rel}" if self.prefix else rel

    def ensure_dir(self, *parts: str) -> str:
        return "/".join(parts)

    def write(self, rel_path: str, data: bytes, offset: int = 0) -> None:
        key = self._key(rel_path)
        if offset == 0:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
            return
        local = os.path.join(self._cache_dir, rel_path.replace("/", "_"))
        os.makedirs(os.path.dirname(local), exist_ok=True)
        if offset and os.path.exists(local):
            with open(local, "r+b") as f:
                f.seek(offset)
                f.write(data)
        else:
            with open(local, "wb") as f:
                f.write(data)
        if os.path.getsize(local) >= offset + len(data):
            with open(local, "rb") as f:
                self.client.put_object(Bucket=self.bucket, Key=key, Body=f.read())

    def read_path(self, rel_path: str) -> str:
        key = self._key(rel_path)
        local = os.path.join(self._cache_dir, rel_path.replace("/", "_"))
        if not os.path.isfile(local):
            os.makedirs(os.path.dirname(local), exist_ok=True)
            self.client.download_file(self.bucket, key, local)
        return local

    def exists(self, rel_path: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(rel_path))
            return True
        except Exception:
            return False

    def save_file(self, rel_path: str, file_obj) -> int:
        key = self._key(rel_path)
        body = file_obj.read()
        self.client.put_object(Bucket=self.bucket, Key=key, Body=body)
        return len(body)

    def size(self, rel_path: str) -> int:
        resp = self.client.head_object(Bucket=self.bucket, Key=self._key(rel_path))
        return resp["ContentLength"]


_backend: StorageBackend | None = None


def get_storage() -> StorageBackend:
    global _backend
    if _backend is not None:
        return _backend
    cfg = current_app.config
    backend = cfg.get("STORAGE_BACKEND", "local")
    if backend == "s3":
        _backend = S3StorageBackend(
            bucket=cfg["S3_BUCKET"],
            prefix=cfg.get("S3_PREFIX", ""),
            endpoint=cfg.get("S3_ENDPOINT"),
            access_key=cfg.get("S3_ACCESS_KEY"),
            secret_key=cfg.get("S3_SECRET_KEY"),
        )
    else:
        _backend = LocalStorageBackend(cfg["UPLOAD_FOLDER"])
    return _backend


def reset_storage():
    global _backend
    _backend = None
