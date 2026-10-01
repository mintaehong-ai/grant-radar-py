"""개발 단계에서 S3의 역할을 대신하는 로컬 파일 저장소입니다."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from grant_radar.domain.notice import Notice


@dataclass(frozen=True, slots=True)
class CollectionPaths:
    """한 수집 실행에서 생성하는 원본 및 가공 데이터 경로입니다."""

    raw_dir: Path
    processed_dir: Path


class LocalCollectionStorage:
    """수집일과 실행 ID로 데이터를 분리해 과거 실행을 덮어쓰지 않습니다."""

    def __init__(self, data_dir: Path, source: str, collected_at: datetime, run_id: str) -> None:
        date_partition = collected_at.date().isoformat()
        self.paths = CollectionPaths(
            raw_dir=data_dir / "raw" / source / date_partition / run_id,
            processed_dir=data_dir / "processed" / source / date_partition / run_id,
        )

    def save_raw_page(self, page: int, body: bytes) -> dict[str, str | int]:
        """API 응답 원문을 저장하고 manifest에 기록할 무결성 정보를 반환합니다."""
        path = self.paths.raw_dir / f"page-{page:05d}.json"
        _atomic_write_bytes(path, body)
        return {
            "page": page,
            "path": str(path),
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
        }

    def save_notices(self, notices: Iterable[Notice]) -> Path:
        """정규화된 공고를 대용량 처리에 적합한 JSON Lines로 저장합니다."""
        path = self.paths.processed_dir / "notices.jsonl"
        lines = (json.dumps(notice.to_dict(), ensure_ascii=False, separators=(",", ":")) for notice in notices)
        content = ("\n".join(lines) + "\n").encode("utf-8")
        _atomic_write_bytes(path, content)
        return path

    def save_manifest(self, manifest: dict[str, object]) -> Path:
        """수집 실행을 재현하는 데 필요한 메타데이터를 저장합니다."""
        path = self.paths.raw_dir / "manifest.json"
        content = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        _atomic_write_bytes(path, content)
        return path


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    """임시 파일을 완성한 뒤 교체해 중간 상태의 파일 노출을 방지합니다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_bytes(content)
    # 같은 파일시스템 안에서 원자적으로 교체하므로 읽는 쪽은 완성된 파일만 보게 됩니다.
    os.replace(temporary_path, path)
