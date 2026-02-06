"""S3/MinIO storage for model artifacts."""
from minio import Minio
from minio.error import S3Error
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
BUCKET_NAME = os.getenv("BUCKET_NAME", "models")


class ModelStorage:
    """Handle model artifact storage in MinIO/S3."""
    
    def __init__(self):
        self.client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE
        )
        self.bucket = BUCKET_NAME
        self._ensure_bucket()
    
    def _ensure_bucket(self):
        """Create bucket if it doesn't exist."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created bucket: {self.bucket}")
        except S3Error as e:
            logger.error(f"Error ensuring bucket exists: {e}")
            raise
    
    def upload_model(self, local_path: str, s3_path: str):
        """Upload model artifact to S3."""
        try:
            self.client.fput_object(self.bucket, s3_path, local_path)
            logger.info(f"Uploaded {local_path} to {self.bucket}/{s3_path}")
            return s3_path
        except S3Error as e:
            logger.error(f"Error uploading model: {e}")
            raise
    
    def download_model(self, s3_path: str, local_path: str):
        """Download model artifact from S3."""
        try:
            self.client.fget_object(self.bucket, s3_path, local_path)
            logger.info(f"Downloaded {self.bucket}/{s3_path} to {local_path}")
            return local_path
        except S3Error as e:
            logger.error(f"Error downloading model: {e}")
            raise
    
    def model_exists(self, s3_path: str) -> bool:
        """Check if model exists in S3."""
        try:
            self.client.stat_object(self.bucket, s3_path)
            return True
        except S3Error:
            return False