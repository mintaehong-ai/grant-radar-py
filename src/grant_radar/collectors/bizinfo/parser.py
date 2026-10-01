"""기업마당 API 응답을 출처 공통 공고 모델로 변환합니다."""

from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape
from typing import Any

from grant_radar.domain.notice import Notice


class ResponseFormatError(ValueError):
    """API 응답이 예상한 구조와 다를 때 발생합니다."""


def parse_page(payload: Any, collected_at: datetime) -> tuple[list[Notice], int]:
    """기업마당 JSON 응답에서 공고 목록과 전체 건수를 추출합니다."""
    if not isinstance(payload, dict):
        raise ResponseFormatError("기업마당 응답 최상위 값은 JSON 객체여야 합니다.")
    channel = payload.get("jsonArray")
    if not isinstance(channel, dict):
        raise ResponseFormatError("기업마당 응답의 jsonArray 필드가 객체가 아닙니다.")
    raw_items = channel.get("item", [])
    if isinstance(raw_items, dict):
        items = [raw_items]
    elif isinstance(raw_items, list):
        items = raw_items
    else:
        raise ResponseFormatError("기업마당 응답의 item 필드가 배열 또는 객체가 아닙니다.")

    notices = [_parse_notice(item, collected_at) for item in items]
    return notices, _total_count(items, len(notices))


def _parse_notice(row: Any, collected_at: datetime) -> Notice:
    """기업마당의 중복 필드명을 우선순위에 따라 공통 필드로 정리합니다."""
    if not isinstance(row, dict):
        raise ResponseFormatError("기업마당 item의 각 항목은 JSON 객체여야 합니다.")
    source_notice_id = _first_text(row, "pblancId", "seq")
    title = _first_text(row, "pblancNm", "title")
    if source_notice_id is None or title is None:
        raise ResponseFormatError("기업마당 공고에 pblancId/seq 또는 공고명이 없습니다.")

    start_date, end_date = _parse_period(_first_text(row, "reqstBeginEndDe", "reqstDt"))
    return Notice(
        source="bizinfo",
        source_notice_id=source_notice_id,
        title=title,
        organization=_first_text(row, "jrsdInsttNm", "author"),
        application_start_date=start_date,
        application_end_date=end_date,
        detail_url=_first_text(row, "pblancUrl", "link"),
        target_summary=_first_text(row, "trgetNm"),
        content=_clean_html(_first_text(row, "bsnsSumryCn", "description")),
        category=_first_text(row, "pldirSportRealmLclasCodeNm", "lcategory"),
        region=_region_from_hashtags(_first_text(row, "hashTags")),
        # 기업마당은 모집 여부 플래그가 없어 신청 마감일 기준으로 파이프라인에서 필터링합니다.
        is_recruiting=None,
        collected_at=collected_at,
        raw=dict(row),
    )


def _total_count(items: list[Any], fallback: int) -> int:
    """각 item에 반복 포함되는 totCnt를 페이지네이션 전체 건수로 사용합니다."""
    if not items:
        return 0
    first = items[0]
    if not isinstance(first, dict):
        return fallback
    value = first.get("totCnt")
    if value in (None, ""):
        return fallback
    try:
        return int(str(value))
    except ValueError as error:
        raise ResponseFormatError(f"기업마당 totCnt 값 {value!r}을 정수로 해석할 수 없습니다.") from error


def _parse_period(value: str | None) -> tuple[date | None, date | None]:
    """'YYYYMMDD ~ YYYYMMDD' 형식의 신청기간에서 시작일과 종료일을 추출합니다."""
    if not value:
        return None, None
    matches = re.findall(r"\d{8}", value)
    if not matches:
        return None, None
    start_date = _parse_yyyymmdd(matches[0])
    end_date = _parse_yyyymmdd(matches[-1]) if len(matches) >= 2 else None
    return start_date, end_date


def _parse_yyyymmdd(value: str) -> date:
    """날짜 문자열 검증 실패를 응답 형식 오류로 명확히 드러냅니다."""
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as error:
        raise ResponseFormatError(f"기업마당 날짜 값 {value!r}은 YYYYMMDD 형식이 아닙니다.") from error


def _first_text(row: dict[str, Any], *keys: str) -> str | None:
    """신/구 응답 필드명이 함께 올 수 있어 먼저 채워진 값을 선택합니다."""
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _clean_html(value: str | None) -> str | None:
    """간단한 HTML 태그를 제거해 변경 비교에 쓰기 쉬운 본문으로 만듭니다."""
    if value is None:
        return None
    text = re.sub(r"<[^>]+>", " ", unescape(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _region_from_hashtags(value: str | None) -> str | None:
    """해시태그 안에 섞인 지역명을 관심 조건 매칭용 지역 필드로 분리합니다."""
    if not value:
        return None
    regions = {
        "서울",
        "부산",
        "대구",
        "인천",
        "전남광주",
        "대전",
        "울산",
        "세종",
        "경기",
        "강원",
        "충북",
        "충남",
        "전북",
        "경북",
        "경남",
        "제주",
    }
    found = [tag.strip() for tag in value.split(",") if tag.strip() in regions]
    return ",".join(found) if found else None
