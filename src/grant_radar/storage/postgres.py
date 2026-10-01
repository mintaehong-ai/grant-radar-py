"""PostgreSQL에 수집 실행, 공고 현재 상태, 버전, 변경 이벤트를 저장합니다."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Iterable

import psycopg
from psycopg.types.json import Jsonb

from grant_radar.domain.notice import Notice
from grant_radar.storage.object_store import StoredObject


class PostgresNoticeRepository:
    """공고의 현재 상태와 변경 이력을 함께 보관하는 저장소입니다."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def save_collection(
        self,
        *,
        source: str,
        run_id: str,
        collected_at: datetime,
        manifest: dict[str, object],
        raw_objects: Iterable[StoredObject],
        processed_objects: Iterable[StoredObject],
        notices: Iterable[Notice],
    ) -> None:
        """한 번의 수집 결과를 트랜잭션으로 저장해 중간 실패 상태를 피합니다."""
        notice_list = list(notices)
        with psycopg.connect(self.database_url) as connection:
            self._ensure_schema(connection)
            with connection.transaction():
                self._insert_run(connection, source, run_id, collected_at, manifest)
                self._insert_objects(connection, run_id, "raw", raw_objects)
                self._insert_objects(connection, run_id, "processed", processed_objects)
                for notice in notice_list:
                    self._upsert_notice(connection, run_id, notice)

    def _ensure_schema(self, connection: psycopg.Connection) -> None:
        """초기 포트폴리오 단계에서는 별도 마이그레이션 없이 필요한 테이블을 준비합니다."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS collection_runs (
                run_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                collected_at TIMESTAMPTZ NOT NULL,
                status TEXT NOT NULL,
                manifest JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS raw_objects (
                id BIGSERIAL PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES collection_runs(run_id),
                object_kind TEXT NOT NULL,
                bucket TEXT NOT NULL,
                object_key TEXT NOT NULL,
                uri TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (bucket, object_key)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notices (
                source TEXT NOT NULL,
                source_notice_id TEXT NOT NULL,
                title TEXT NOT NULL,
                organization TEXT,
                application_start_date DATE,
                application_end_date DATE,
                detail_url TEXT,
                target_summary TEXT,
                content TEXT,
                category TEXT,
                region TEXT,
                is_recruiting BOOLEAN,
                current_hash TEXT NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL,
                last_seen_at TIMESTAMPTZ NOT NULL,
                raw JSONB NOT NULL,
                PRIMARY KEY (source, source_notice_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notice_versions (
                id BIGSERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                source_notice_id TEXT NOT NULL,
                run_id TEXT NOT NULL REFERENCES collection_runs(run_id),
                content_hash TEXT NOT NULL,
                collected_at TIMESTAMPTZ NOT NULL,
                snapshot JSONB NOT NULL,
                UNIQUE (source, source_notice_id, content_hash)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notice_changes (
                id BIGSERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                source_notice_id TEXT NOT NULL,
                run_id TEXT NOT NULL REFERENCES collection_runs(run_id),
                field_name TEXT NOT NULL,
                old_value JSONB,
                new_value JSONB,
                detected_at TIMESTAMPTZ NOT NULL
            )
            """
        )

    def _insert_run(
        self,
        connection: psycopg.Connection,
        source: str,
        run_id: str,
        collected_at: datetime,
        manifest: dict[str, object],
    ) -> None:
        connection.execute(
            """
            INSERT INTO collection_runs (run_id, source, collected_at, status, manifest)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (run_id) DO UPDATE
            SET status = EXCLUDED.status, manifest = EXCLUDED.manifest
            """,
            (run_id, source, collected_at, manifest.get("status", "succeeded"), Jsonb(manifest)),
        )

    def _insert_objects(
        self,
        connection: psycopg.Connection,
        run_id: str,
        object_kind: str,
        objects: Iterable[StoredObject],
    ) -> None:
        for stored_object in objects:
            connection.execute(
                """
                INSERT INTO raw_objects (run_id, object_kind, bucket, object_key, uri, sha256, size_bytes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (bucket, object_key) DO NOTHING
                """,
                (
                    run_id,
                    object_kind,
                    stored_object.bucket,
                    stored_object.key,
                    stored_object.uri,
                    stored_object.sha256,
                    stored_object.size_bytes,
                ),
            )

    def _upsert_notice(self, connection: psycopg.Connection, run_id: str, notice: Notice) -> None:
        snapshot = notice.to_dict()
        content_hash = _notice_hash(snapshot)
        existing = connection.execute(
            """
            SELECT title, organization, application_start_date, application_end_date,
                   detail_url, target_summary, content, category, region, is_recruiting, current_hash
            FROM notices
            WHERE source = %s AND source_notice_id = %s
            """,
            (notice.source, notice.source_notice_id),
        ).fetchone()

        if existing is not None:
            self._insert_changes(connection, run_id, notice, existing, snapshot)

        connection.execute(
            """
            INSERT INTO notices (
                source, source_notice_id, title, organization, application_start_date,
                application_end_date, detail_url, target_summary, content, category,
                region, is_recruiting, current_hash, first_seen_at, last_seen_at, raw
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_notice_id) DO UPDATE SET
                title = EXCLUDED.title,
                organization = EXCLUDED.organization,
                application_start_date = EXCLUDED.application_start_date,
                application_end_date = EXCLUDED.application_end_date,
                detail_url = EXCLUDED.detail_url,
                target_summary = EXCLUDED.target_summary,
                content = EXCLUDED.content,
                category = EXCLUDED.category,
                region = EXCLUDED.region,
                is_recruiting = EXCLUDED.is_recruiting,
                current_hash = EXCLUDED.current_hash,
                last_seen_at = EXCLUDED.last_seen_at,
                raw = EXCLUDED.raw
            """,
            (
                notice.source,
                notice.source_notice_id,
                notice.title,
                notice.organization,
                notice.application_start_date,
                notice.application_end_date,
                notice.detail_url,
                notice.target_summary,
                notice.content,
                notice.category,
                notice.region,
                notice.is_recruiting,
                content_hash,
                notice.collected_at,
                notice.collected_at,
                Jsonb(notice.raw),
            ),
        )
        connection.execute(
            """
            INSERT INTO notice_versions (source, source_notice_id, run_id, content_hash, collected_at, snapshot)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_notice_id, content_hash) DO NOTHING
            """,
            (notice.source, notice.source_notice_id, run_id, content_hash, notice.collected_at, Jsonb(snapshot)),
        )

    def _insert_changes(
        self,
        connection: psycopg.Connection,
        run_id: str,
        notice: Notice,
        existing: tuple[object, ...],
        snapshot: dict[str, object],
    ) -> None:
        """알림에 바로 쓸 수 있는 필드 단위 변경 이벤트를 기록합니다."""
        field_names = (
            "title",
            "organization",
            "application_start_date",
            "application_end_date",
            "detail_url",
            "target_summary",
            "content",
            "category",
            "region",
            "is_recruiting",
        )
        old_values = dict(zip(field_names, existing[:-1], strict=True))
        old_hash = existing[-1]
        new_hash = _notice_hash(snapshot)
        if old_hash == new_hash:
            return
        for field_name in field_names:
            old_value = _json_value(old_values[field_name])
            new_value = _json_value(snapshot[field_name])
            if old_value == new_value:
                continue
            connection.execute(
                """
                INSERT INTO notice_changes (source, source_notice_id, run_id, field_name, old_value, new_value, detected_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    notice.source,
                    notice.source_notice_id,
                    run_id,
                    field_name,
                    Jsonb(old_value),
                    Jsonb(new_value),
                    notice.collected_at,
                ),
            )


def _notice_hash(snapshot: dict[str, object]) -> str:
    """수집 시각을 제외한 공고 내용이 바뀌었는지 판단하는 해시를 만듭니다."""
    comparable = {key: value for key, value in snapshot.items() if key != "collected_at"}
    content = json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _json_value(value: object) -> object:
    """date/datetime 값을 JSONB에 넣을 수 있는 문자열로 정규화합니다."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
