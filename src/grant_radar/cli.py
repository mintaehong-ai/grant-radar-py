"""개발자와 배치 실행 환경에서 공통으로 사용하는 명령행 진입점입니다."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from grant_radar.collectors.bizinfo.parser import ResponseFormatError as BizinfoResponseFormatError
from grant_radar.collectors.bizinfo.parser import parse_page as parse_bizinfo_page
from grant_radar.collectors.kstartup.parser import ResponseFormatError as KStartupResponseFormatError
from grant_radar.collectors.kstartup.parser import parse_page as parse_kstartup_page
from grant_radar.config import BizinfoSettings, ConfigurationError, KStartupSettings
from grant_radar.pipelines.bizinfo import collect_bizinfo
from grant_radar.pipelines.kstartup import collect_kstartup


def build_parser() -> argparse.ArgumentParser:
    """수집 실행과 저장된 응답 검증에 필요한 하위 명령을 정의합니다."""
    parser = argparse.ArgumentParser(prog="grant-radar", description="지원사업 공고 수집 파이프라인")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="외부 API에서 공고를 수집합니다.")
    collect_parser.add_argument("source", choices=["kstartup", "bizinfo"])

    parse_parser = subparsers.add_parser("parse-kstartup", help="저장된 K-Startup 응답 형식을 검증합니다.")
    parse_parser.add_argument("path", type=Path)
    parse_bizinfo_parser = subparsers.add_parser("parse-bizinfo", help="저장된 기업마당 응답 형식을 검증합니다.")
    parse_bizinfo_parser.add_argument("path", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """명령을 실행하고 셸에서 사용할 종료 코드를 반환합니다."""
    args = build_parser().parse_args(argv)
    try:
        if args.command == "collect":
            # 설정 로딩부터 전체 페이지 수집 및 저장까지 한 번의 실행 단위로 처리합니다.
            if args.source == "kstartup":
                result = collect_kstartup(KStartupSettings.from_env())
            else:
                result = collect_bizinfo(BizinfoSettings.from_env())
            print(json.dumps(result.__dict__ if hasattr(result, "__dict__") else {
                "run_id": result.run_id,
                "notice_count": result.notice_count,
                "page_count": result.page_count,
                "manifest_path": result.manifest_path,
                "notices_path": result.notices_path,
            }, ensure_ascii=False, indent=2))
            return 0

        # 실제 API 호출 전에 내려받은 샘플이 현재 파서와 호환되는지 확인하는 용도입니다.
        payload = json.loads(args.path.read_text(encoding="utf-8-sig"))
        if args.command == "parse-kstartup":
            notices, match_count = parse_kstartup_page(payload, datetime.now(UTC))
        else:
            notices, match_count = parse_bizinfo_page(payload, datetime.now(UTC))
        print(json.dumps({"parsed_count": len(notices), "match_count": match_count}, ensure_ascii=False))
        return 0
    except (
        ConfigurationError,
        KStartupResponseFormatError,
        BizinfoResponseFormatError,
        OSError,
        json.JSONDecodeError,
        RuntimeError,
    ) as error:
        # 배치 도구가 실패를 감지할 수 있도록 오류 메시지는 stderr, 종료 코드는 1로 반환합니다.
        print(f"오류: {error}", file=sys.stderr)
        return 1
