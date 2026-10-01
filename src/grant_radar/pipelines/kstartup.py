"""K-Startup의 전체 페이지를 수집하고 원본과 정규화 결과를 저장합니다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from grant_radar.collectors.kstartup.client import KStartupClient
from grant_radar.collectors.kstartup.parser import parse_page
from grant_radar.config import KStartupSettings
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


def collect_kstartup(settings: KStartupSettings) -> CollectionResult:
    """K-Startup 전체 공고를 하나의 추적 가능한 실행 단위로 수집합니다."""
    collected_at = datetime.now(UTC)
    # 같은 초에 여러 번 실행해도 경로가 겹치지 않도록 짧은 UUID를 덧붙입니다.
    run_id = f"{collected_at:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    storage = LocalCollectionStorage(settings.data_dir, "kstartup", collected_at, run_id)
    object_store = _build_object_store(settings)
    repository = _build_repository(settings)
    client = KStartupClient(
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
    match_count: int | None = None
    source_total_count: int | None = None
    received_notice_count = 0

    # 저장 건수가 아닌 API 수신 건수를 기준으로 페이지를 넘겨 필터링과 중복 제거의 영향을 분리합니다.
    while match_count is None or received_notice_count < match_count:
        raw_page = client.fetch_page(page)
        # 파싱보다 원본 저장을 먼저 수행해 변환 실패 시에도 문제 응답을 조사할 수 있게 합니다.
        raw_page_record = storage.save_raw_page(page, raw_page.body)
        if object_store is not None:
            object_key = _object_key("raw", "kstartup", collected_at, run_id, f"page-{page:05d}.json")
            stored_object = object_store.put_raw(object_key, raw_page.body)
            raw_objects.append(stored_object)
            raw_page_record["s3_uri"] = stored_object.uri
        raw_pages.append(raw_page_record)
        page_notices, page_match_count = parse_page(raw_page.payload, collected_at)
        match_count = page_match_count
        source_total_count = raw_page.payload.get("totalCount")
        received_notice_count += len(page_notices)

        if not page_notices:
            # API의 전체 건수가 실제 페이지와 어긋나도 빈 페이지에서 안전하게 종료합니다.
            break
        for notice in page_notices:
            # API가 모집 여부 필터를 무시하더라도 종료된 공고는 가공 데이터에 저장하지 않습니다.
            if notice.is_recruiting is not True:
                continue
            # 동일 실행 안에서 API가 중복 행을 돌려줘도 공고 ID당 하나만 남깁니다.
            notices_by_id[notice.source_notice_id] = notice
        page += 1

    notices_path = storage.save_notices(notices_by_id.values())
    processed_objects: list[StoredObject] = []
    if object_store is not None:
        notices_body = notices_path.read_bytes()
        notices_key = _object_key("processed", "kstartup", collected_at, run_id, "notices.jsonl")
        processed_objects.append(
            object_store.put_processed(notices_key, notices_body, content_type="application/x-ndjson")
        )
    # manifest는 실행 결과와 각 원본 파일의 무결성을 한곳에서 추적하기 위한 메타데이터입니다.
    manifest = {
        "schema_version": 1,
        "source": "kstartup",
        "run_id": run_id,
        "collected_at": collected_at.isoformat(),
        "status": "succeeded",
        "collection_scope": {"recruiting_only": True},
        "api_total_count": source_total_count,
        "api_match_count": match_count,
        "received_notice_count": received_notice_count,
        "collected_notice_count": len(notices_by_id),
        "page_count": len(raw_pages),
        "raw_pages": raw_pages,
        "notices_path": str(notices_path),
    }
    manifest_path = storage.save_manifest(manifest)
    if object_store is not None:
        manifest_body = manifest_path.read_bytes()
        manifest_key = _object_key("raw", "kstartup", collected_at, run_id, "manifest.json")
        raw_objects.append(object_store.put_raw(manifest_key, manifest_body))
    if repository is not None:
        repository.save_collection(
            source="kstartup",
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


def _build_object_store(settings: KStartupSettings) -> "S3ObjectStore | None":
    """hybrid 모드에서만 MinIO/S3 저장소를 생성해 로컬 실행의 부담을 줄입니다."""
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


def _build_repository(settings: KStartupSettings) -> "PostgresNoticeRepository | None":
    """hybrid 모드에서만 PostgreSQL 저장소를 연결합니다."""
    if settings.persistence != "hybrid":
        return None
    try:
        from grant_radar.storage.postgres import PostgresNoticeRepository
    except ImportError as error:
        raise RuntimeError("hybrid 저장을 사용하려면 python -m pip install -e . 로 의존성을 설치해야 합니다.") from error

    return PostgresNoticeRepository(settings.database_url or "")


def _object_key(kind: str, source: str, collected_at: datetime, run_id: str, filename: str) -> str:
    """S3 경로도 로컬 파티션과 맞춰 추적과 재처리를 쉽게 합니다."""
    date_partition = collected_at.date().isoformat()
    return f"{kind}/{source}/{date_partition}/{run_id}/{filename}"
