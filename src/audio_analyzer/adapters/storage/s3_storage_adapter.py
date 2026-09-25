import os
import uuid
from pathlib import Path
from typing import Optional

from audio_analyzer.domain.interfaces import IAudioStorage


class S3StorageAdapter(IAudioStorage):
    """
    AWS S3 / MinIO Nesne Depolama (Object Storage) Adaptörü.
    Bulut nesne depolama sağlayıcıları (AWS S3, DigitalOcean Spaces, MinIO)
    üzerinden ses dosyalarını s3:// URI formatı ile saklar ve indirir.
    """

    def __init__(
        self,
        bucket_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        region_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        local_cache_dir: str = "storage/cache",
    ):
        self.bucket_name = bucket_name or os.getenv("S3_BUCKET_NAME", "ses-analizi-storage")
        self.aws_access_key_id = aws_access_key_id or os.getenv("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = aws_secret_access_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        self.region_name = region_name or os.getenv("AWS_REGION", "us-east-1")
        self.endpoint_url = endpoint_url or os.getenv("S3_ENDPOINT_URL")
        self.local_cache_dir = Path(local_cache_dir)
        self.local_cache_dir.mkdir(parents=True, exist_ok=True)
        self._s3_client = None

    def _get_client(self):
        if self._s3_client is None:
            try:
                import boto3

                kwargs = {"region_name": self.region_name}
                if self.aws_access_key_id and self.aws_secret_access_key:
                    kwargs["aws_access_key_id"] = self.aws_access_key_id
                    kwargs["aws_secret_access_key"] = self.aws_secret_access_key
                if self.endpoint_url:
                    kwargs["endpoint_url"] = self.endpoint_url

                self._s3_client = boto3.client("s3", **kwargs)
            except ImportError:
                raise ImportError(
                    "boto3 kütüphanesi yüklü değil. S3 depolama adaptörünü kullanmak için 'pip install boto3' çalıştırın."
                )
        return self._s3_client

    def save(self, file_bytes: bytes, file_name: str) -> str:
        client = self._get_client()
        unique_prefix = uuid.uuid4().hex[:8]
        object_key = f"raw_audio/{unique_prefix}_{file_name}"

        client.put_object(
            Bucket=self.bucket_name,
            Key=object_key,
            Body=file_bytes,
        )

        return f"s3://{self.bucket_name}/{object_key}"

    def get_path(self, storage_uri: str) -> str:
        """
        s3://bucket/key URI'sini okuyup yerel önbelleğe (cache) indirir ve dosya yolunu döner.
        """
        if not storage_uri.startswith("s3://"):
            return storage_uri

        parts = storage_uri.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        object_key = parts[1] if len(parts) > 1 else ""

        cache_filename = Path(object_key).name
        local_path = self.local_cache_dir / cache_filename

        if not local_path.exists():
            client = self._get_client()
            client.download_file(bucket, object_key, str(local_path))

        return str(local_path.absolute())

    def get_bytes(self, storage_uri: str) -> bytes:
        """
        s3://bucket/key URI'sini doğrudan S3/MinIO RAM bellek tamponuna aktarır.
        Fiziksel diske hiç yazmadan 0-Disk I/O ile RAM'e yükler.
        """
        if not storage_uri.startswith("s3://"):
            raise ValueError(f"Geçersiz S3 URI formatı: {storage_uri}")

        parts = storage_uri.replace("s3://", "").split("/", 1)
        bucket = parts[0]
        object_key = parts[1] if len(parts) > 1 else ""

        client = self._get_client()
        response = client.get_object(Bucket=bucket, Key=object_key)
        return response["Body"].read()

    def delete(self, storage_uri: str) -> bool:
        if not storage_uri.startswith("s3://"):
            return False

        try:
            parts = storage_uri.replace("s3://", "").split("/", 1)
            bucket = parts[0]
            object_key = parts[1] if len(parts) > 1 else ""

            client = self._get_client()
            client.delete_object(Bucket=bucket, Key=object_key)
            return True
        except Exception:
            return False
