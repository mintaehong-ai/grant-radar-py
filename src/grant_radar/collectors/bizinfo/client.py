"""기업마당 지원사업정보 API와 통신하는 HTTP 클라이언트입니다."""

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


class BizinfoClient:
    """인증키, JSON 응답 형식, 페이지네이션 파라미터를 캡슐화합니다."""

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
        """지정한 페이지를 요청하고 수신한 원본 바이트를 보존합니다."""
        url = self._build_url(page)
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "grant-radar/0.1"})
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    # 원본 저장을 위해 응답 바이트는 재가공하지 않고 그대로 유지합니다.
                    body = response.read()
                payload = json.loads(body.decode("utf-8-sig"))
                if not isinstance(payload, dict):
                    raise CollectionError("기업마당 응답 최상위 값이 JSON 객체가 아닙니다.")
                return RawPage(page=page, body=body, payload=payload)
            except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
                last_error = error
                if attempt < self.max_retries:
                    # 일시적인 네트워크 오류를 흡수하되, 실패가 길어지면 배치가 실패하도록 둡니다.
                    time.sleep(2 ** (attempt - 1))

        raise CollectionError(f"기업마당 {page}페이지 요청이 {self.max_retries}회 실패했습니다: {last_error}") from last_error

    def _build_url(self, page: int) -> str:
        """문서에 명시된 crtfcKey/dataType/pageUnit/pageIndex 파라미터를 구성합니다."""
        parts = urlsplit(self.api_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query.update(
            {
                "crtfcKey": self.api_key,
                "dataType": "json",
                "pageUnit": str(self.page_size),
                "pageIndex": str(page),
            }
        )
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, safe="%"), parts.fragment))
