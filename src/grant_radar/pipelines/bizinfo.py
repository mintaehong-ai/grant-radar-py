"""기업마당의 전체 페이지를 수집하고 원본과 정규화 결과를 저장합니다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from grant_radar.collectors.bizinfo.client import BizinfoClient
from grant_radar.collectors.bizinfo.parser import parse_page
from grant_radar.config import BizinfoSettings
from grant_radar.domain.notice import Notice
from grant_radar.storage.local import LocalCollectionStorage

if TYPE_CHECKING:
    from grant_radar.storage.object_store import S3ObjectStore, StoredObject
    from grant_radar.storage.postgres import PostgresNoticeRepository


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """CLI와 향후 스케줄러가 사용할 수집 실행 결과 요약입니다."""

    run_id: str
    notice_count: int
    page_count: int
    manifest_path: str
    notices_path: str


def collect_bizinfo(settings: BizinfoSettings) -> CollectionResult:
    """기업마당 지원사업 공고를 하나의 추적 가능한 실행 단위로 수집합니다."""
    collected_at = datetime.now(UTC)
    run_id = f"{collected_at:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    source = "bizinfo"
    storage = LocalCollectionStorage(settings.data_dir, source, collected_at, run_id)
    object_store = _build_object_store(settings)
    repository = _build_repository(settings)
    client = BizinfoClient(
        api_url=settings.api_url,
        api_key=settings.api_key,
        page_size=settings.page_size,
        timeout_seconds=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )

    notices_by_id: dict[str, Notice] = {}
    raw_pages: list[dict[str, str | int]] = []
    raw_objects: list[StoredObject] = []
    page = 1
    total_count: int | None = None
    received_notice_count = 0

    while total_count is None or received_notice_count < total_count:
        raw_page = client.fetch_page(page)
        raw_page_record = storage.save_raw_page(page, raw_page.body)
        if object_store is not None:
            object_key = _object_key("raw", source, collected_at, run_id, f"page-{page:05d}.json")
            stored_object = object_store.put_raw(object_key, raw_page.body)
            raw_objects.append(stored_object)
            raw_page_record["s3_uri"] = stored_object.uri
        raw_pages.append(raw_page_record)

        page_notices, page_total_count = parse_page(raw_page.payload, collected_at)
        total_count = page_total_count
        received_notice_count += len(page_notices)
        if not page_notices:
            # 전체 건수가 잘못 내려와도 빈 페이지에서 무한 루프를 끊습니다.
            break

        for notice in page_notices:
            # 기업마당은 모집 플래그가 없어 마감일이 지난 공고는 현재 관심 공고에서 제외합니다.
            if notice.application_end_date is not None and notice.application_end_date < collected_at.date():
                continue
            notices_by_id[notice.source_notice_id] = notice
        page += 1

    notices_path = storage.save_notices(notices_by_id.values())
    processed_objects: list[StoredObject] = []
    if object_store is not None:
        notices_key = _object_key("processed", source, collected_at, run_id, "notices.jsonl")
        processed_objects.append(
            object_store.put_processed(notices_key, notices_path.read_bytes(), content_type="application/x-ndjson")
        )

    manifest = {
        "schema_version": 1,
        "source": source,
        "run_id": run_id,
        "collected_at": collected_at.isoformat(),
        "status": "succeeded",
        "collection_scope": {"exclude_ended_by_application_end_date": True},
        "api_total_count": total_count,
        "received_notice_count": received_notice_count,
        "collected_notice_count": len(notices_by_id),
        "page_count": len(raw_pages),
        "raw_pages": raw_pages,
        "notices_path": str(notices_path),
    }
    manifest_path = storage.save_manifest(manifest)
    if object_store is not None:
        manifest_key = _object_key("raw", source, collected_at, run_id, "manifest.json")
        raw_objects.append(object_store.put_raw(manifest_key, manifest_path.read_bytes()))
    if repository is not None:
        repository.save_collection(
            source=source,
            run_id=run_id,
            collected_at=collected_at,
            manifest=manifest,
            raw_objects=raw_objects,
            processed_objects=processed_objects,
            notices=notices_by_id.values(),
        )

    return CollectionResult(
        run_id=run_id,
        notice_count=len(notices_by_id),
        page_count=len(raw_pages),
        manifest_path=str(manifest_path),
        notices_path=str(notices_path),
    )


def _build_object_store(settings: BizinfoSettings) -> "S3ObjectStore | None":
    """hybrid 모드에서만 S3 호환 저장소를 생성합니다."""
    if settings.persistence != "hybrid":
        return None
    try:
        from grant_radar.storage.object_store import S3ObjectStore
    except ImportError as error:
        raise RuntimeError("hybrid 저장을 사용하려면 python -m pip install -e . 로 의존성을 설치해야 합니다.") from error
    return S3ObjectStore(
        endpoint_url=settings.s3_endpoint_url or "",
        access_key_id=settings.s3_access_key_id or "",
        secret_access_key=settings.s3_secret_access_key or "",
        raw_bucket=settings.s3_bucket_raw or "",
        processed_bucket=settings.s3_bucket_processed or "",
    )


def _build_repository(settings: BizinfoSettings) -> "PostgresNoticeRepository | None":
    """hybrid 모드에서만 PostgreSQL 저장소를 연결합니다."""
    if settings.persistence != "hybrid":
        return None
    try:
        from grant_radar.storage.postgres import PostgresNoticeRepository
    except ImportError as error:
        raise RuntimeError("hybrid 저장을 사용하려면 python -m pip install -e . 로 의존성을 설치해야 합니다.") from error
    return PostgresNoticeRepository(settings.database_url or "")


def _object_key(kind: str, source: str, collected_at: datetime, run_id: str, filename: str) -> str:
    """S3 경로를 로컬 파티션과 같은 규칙으로 맞춥니다."""
    date_partition = collected_at.date().isoformat()
    return f"{kind}/{source}/{date_partition}/{run_id}/{filename}"
