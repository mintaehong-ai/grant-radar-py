"""K-Startup 전용 필드명을 출처 공통 공고 모델로 변환합니다."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from grant_radar.domain.notice import Notice


class ResponseFormatError(ValueError):
    """API 응답이 예상한 계약과 다를 때 발생합니다."""


def parse_page(payload: Any, collected_at: datetime) -> tuple[list[Notice], int]:
    """페이지 응답을 검증하고 공고 목록과 검색 조건에 일치하는 건수를 반환합니다."""
    # 필수 구조를 초기에 검사해 일부 필드만 저장된 불완전한 실행을 막습니다.
    if not isinstance(payload, dict):
        raise ResponseFormatError("응답 최상위 값은 JSON 객체여야 합니다.")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ResponseFormatError("응답의 data 필드가 배열이 아닙니다.")

    total_count = payload.get("totalCount")
    if not isinstance(total_count, int) or total_count < 0:
        raise ResponseFormatError("응답의 totalCount가 0 이상의 정수가 아닙니다.")

    # totalCount는 전체 데이터 수이고 matchCount가 요청 조건에 맞는 실제 페이지네이션 대상입니다.
    match_count = payload.get("matchCount", total_count)
    if not isinstance(match_count, int) or match_count < 0:
        raise ResponseFormatError("응답의 matchCount가 0 이상의 정수가 아닙니다.")

    return [_parse_notice(row, collected_at) for row in rows], match_count


def _parse_notice(row: Any, collected_at: datetime) -> Notice:
    """API 공고 한 건을 변경 비교에 사용할 공통 필드로 정규화합니다."""
    if not isinstance(row, dict):
        raise ResponseFormatError("data의 각 항목은 JSON 객체여야 합니다.")
    source_notice_id = row.get("pbanc_sn")
    title = row.get("biz_pbanc_nm")
    if source_notice_id is None or not isinstance(title, str) or not title.strip():
        raise ResponseFormatError("공고에 pbanc_sn 또는 biz_pbanc_nm이 없습니다.")

    return Notice(
        source="kstartup",
        source_notice_id=str(source_notice_id),
        title=title.strip(),
        organization=_optional_text(row.get("pbanc_ntrp_nm")),
        application_start_date=_parse_date(row.get("pbanc_rcpt_bgng_dt")),
        application_end_date=_parse_date(row.get("pbanc_rcpt_end_dt")),
        detail_url=_optional_text(row.get("detl_pg_url")),
        target_summary=_optional_text(row.get("aply_trgt_ctnt")),
        content=_optional_text(row.get("pbanc_ctnt")),
        category=_optional_text(row.get("supt_biz_clsfc")),
        region=_optional_text(row.get("supt_regin")),
        is_recruiting=_parse_yes_no(row.get("rcrt_prgs_yn")),
        collected_at=collected_at,
        # 알려지지 않은 필드도 버리지 않아 스키마 변경과 후속 가공에 대비합니다.
        raw=dict(row),
    )


def _parse_date(value: Any) -> date | None:
    """API의 YYYYMMDD 문자열을 날짜로 변환하며 빈 값은 허용합니다."""
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value), "%Y%m%d").date()
    except ValueError as error:
        raise ResponseFormatError(f"날짜 값 {value!r}은 YYYYMMDD 형식이 아닙니다.") from error


def _parse_yes_no(value: Any) -> bool | None:
    """모집 여부의 Y/N 값을 불리언으로 변환하며 빈 값은 미확정으로 둡니다."""
    if value in (None, ""):
        return None
    normalized = str(value).upper()
    if normalized == "Y":
        return True
    if normalized == "N":
        return False
    raise ResponseFormatError(f"Y/N 값 {value!r}을 해석할 수 없습니다.")


def _optional_text(value: Any) -> str | None:
    """선택 텍스트의 앞뒤 공백을 제거하고 빈 문자열은 None으로 통일합니다."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
