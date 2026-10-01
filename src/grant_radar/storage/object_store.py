"""MinIO 또는 S3에 원본 파일을 저장하는 어댑터입니다."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import boto3


@dataclass(frozen=True, slots=True)
class StoredObject:
    """DB에 함께 기록할 객체 저장 결과입니다."""

    bucket: str
    key: str
    uri: str
    sha256: str
    size_bytes: int


class S3ObjectStore:
    """S3 호환 API를 사용하므로 로컬 MinIO와 AWS S3를 같은 코드로 다룹니다."""

    def __init__(
        self,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        raw_bucket: str,
        processed_bucket: str,
    ) -> None:
        self.raw_bucket = raw_bucket
        self.processed_bucket = processed_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="us-east-1",
        )

    def put_raw(self, key: str, body: bytes, content_type: str = "application/json") -> StoredObject:
        """API 응답, HTML, 첨부파일처럼 재처리 가능한 원본 데이터를 저장합니다."""
        return self._put(self.raw_bucket, key, body, content_type)

    def put_processed(self, key: str, body: bytes, content_type: str = "application/json") -> StoredObject:
        """정규화 JSONL이나 향후 Parquet처럼 분석용 산출물을 저장합니다."""
        return self._put(self.processed_bucket, key, body, content_type)

    def _put(self, bucket: str, key: str, body: bytes, content_type: str) -> StoredObject:
        digest = hashlib.sha256(body).hexdigest()
        self._client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)
        return StoredObject(
            bucket=bucket,
            key=key,
            uri=f"s3://{bucket}/{key}",
            sha256=digest,
            size_bytes=len(body),
        )
