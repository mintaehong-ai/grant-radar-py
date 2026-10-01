"""K-Startup 공고 API와 통신하고 응답 원문을 보존하는 HTTP 클라이언트입니다."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class CollectionError(RuntimeError):
    """API 요청을 완료할 수 없을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class RawPage:
    """원본 저장용 바이트와 파싱용 JSON을 함께 전달하는 페이지 응답입니다."""

    page: int
    body: bytes
    payload: dict[str, Any]


class KStartupClient:
    """인증, 페이지네이션 파라미터, 재시도 정책을 캡슐화합니다."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        page_size: int,
        timeout_seconds: float,
        max_retries: int,
    ) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.page_size = page_size
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def fetch_page(self, page: int) -> RawPage:
        """지정한 페이지를 요청하고 원본 바이트와 JSON 객체를 반환합니다."""
        url = self._build_url(page)
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "grant-radar/0.1"})
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    # 재직렬화하면 공백이나 키 순서가 바뀌므로 수신한 바이트를 그대로 유지합니다.
                    body = response.read()
                payload = json.loads(body.decode("utf-8-sig"))
                if not isinstance(payload, dict):
                    raise CollectionError("API 응답 최상위 값이 JSON 객체가 아닙니다.")
                return RawPage(page=page, body=body, payload=payload)
            except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
                last_error = error
                if attempt < self.max_retries:
                    # 짧은 지수 백오프로 일시적인 네트워크 오류를 흡수합니다.
                    time.sleep(2 ** (attempt - 1))

        # 마지막 예외를 메시지에 포함해 컨테이너 네트워크, 인증키, API 오류를 빠르게 구분합니다.
        raise CollectionError(f"{page}페이지 요청이 {self.max_retries}회 실패했습니다: {last_error}") from last_error

    def _build_url(self, page: int) -> str:
        """기존 URL 쿼리를 보존하면서 공통 조회 파라미터를 추가합니다."""
        parts = urlsplit(self.api_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(
            {
                "page": str(page),
                "perPage": str(self.page_size),
                "returnType": "json",
                # 공공데이터포털 GW 조건식으로 모집 중인 공고만 정확히 조회합니다.
                "cond[rcrt_prgs_yn::EQ]": "Y",
                # 공공데이터포털 규약상 요청 파라미터 이름은 ServiceKey로 고정되어 있습니다.
                "ServiceKey": self.api_key,
            }
        )
        # 인증키가 이미 인코딩된 경우 이중 인코딩하지 않도록 '%'를 보존합니다.
        encoded_query = urlencode(query, safe="%")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, encoded_query, parts.fragment))
