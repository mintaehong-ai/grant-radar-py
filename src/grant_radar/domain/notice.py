"""여러 수집 출처가 함께 사용할 공고 도메인 모델입니다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Notice:
    """출처별 원본은 보존하면서 변경 비교에 필요한 공통 필드를 제공합니다."""

    source: str
    source_notice_id: str
    title: str
    organization: str | None
    application_start_date: date | None
    application_end_date: date | None
    detail_url: str | None
    target_summary: str | None
    content: str | None
    category: str | None
    region: str | None
    is_recruiting: bool | None
    collected_at: datetime
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """파일 저장이 가능한 JSON 호환 사전으로 변환합니다."""
        value = asdict(self)
        # JSON 직렬화 시 날짜 표현을 항상 ISO 8601로 고정합니다.
        for key in ("application_start_date", "application_end_date", "collected_at"):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        return value
