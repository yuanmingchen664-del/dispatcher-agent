import hashlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO, Optional, Protocol

import boto3

from backend.app.core.config import Settings


@dataclass
class StoredObject:
    provider: str
    bucket: Optional[str]
    object_key: str
    file_hash: str
    file_size: int


class Storage(Protocol):
    def save(self, fileobj: BinaryIO, filename: str) -> StoredObject:
        ...

    def download_to_temp(self, object_key: str) -> str:
        ...


class LocalStorage:
    def __init__(self, root_dir: str):
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, fileobj: BinaryIO, filename: str) -> StoredObject:
        object_key = f"{uuid.uuid4()}-{Path(filename).name}"
        path = self.root / object_key
        digest = hashlib.sha256()
        size = 0
        with path.open("wb") as output:
            while chunk := fileobj.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                output.write(chunk)
        return StoredObject("local", None, object_key, digest.hexdigest(), size)

    def download_to_temp(self, object_key: str) -> str:
        source = self.root / object_key
        temp = NamedTemporaryFile(delete=False, suffix=Path(object_key).suffix)
        temp.close()
        shutil.copyfile(source, temp.name)
        return temp.name


class S3Storage:
    def __init__(self, settings: Settings):
        if not settings.s3_bucket:
            raise ValueError("S3_BUCKET is required when STORAGE_PROVIDER=s3")
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
        )

    def save(self, fileobj: BinaryIO, filename: str) -> StoredObject:
        object_key = f"manuals/{uuid.uuid4()}-{Path(filename).name}"
        digest = hashlib.sha256()
        size = 0
        temp = NamedTemporaryFile(delete=False)
        try:
            with open(temp.name, "wb") as output:
                while chunk := fileobj.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
            self.client.upload_file(temp.name, self.bucket, object_key)
        finally:
            Path(temp.name).unlink(missing_ok=True)
        return StoredObject("s3", self.bucket, object_key, digest.hexdigest(), size)

    def download_to_temp(self, object_key: str) -> str:
        temp = NamedTemporaryFile(delete=False, suffix=Path(object_key).suffix)
        temp.close()
        self.client.download_file(self.bucket, object_key, temp.name)
        return temp.name


def get_storage(settings: Settings) -> Storage:
    if settings.storage_provider == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.local_storage_dir)
