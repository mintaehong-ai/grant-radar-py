"""환경변수를 실행에 필요한 타입으로 검증하고 변환합니다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_KSTARTUP_API_URL = (
    "https://apis.data.go.kr/B552735/"
    "kisedKstartupService01/getAnnouncementInformation01"
)


class ConfigurationError(ValueError):
    """필수 설정이 없거나 잘못됐을 때 발생합니다."""


@dataclass(frozen=True, slots=True)
class KStartupSettings:
    """K-Startup 한 번의 수집 실행에 필요한 설정 모음입니다."""

    api_url: str
    api_key: str
    page_size: int = 100
    timeout_seconds: float = 30.0
    max_retries: int = 3
    data_dir: Path = Path("data")
    persistence: str = "local"
    database_url: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket_raw: str | None = None
    s3_bucket_processed: str | None = None

    @classmethod
    def from_env(cls) -> "KStartupSettings":
        """`.env`와 시스템 환경변수를 읽어 검증된 설정을 만듭니다."""
        _load_dotenv(Path(".env"))
        api_url = os.getenv("KSTARTUP_API_URL", DEFAULT_KSTARTUP_API_URL).strip()
        api_key = os.getenv("KSTARTUP_API_KEY", "").strip()
        if not api_key:
            raise ConfigurationError("KSTARTUP_API_KEY 환경변수가 필요합니다.")

        page_size = _positive_int("KSTARTUP_PAGE_SIZE", 100)
        if page_size > 100:
            raise ConfigurationError("KSTARTUP_PAGE_SIZE는 API 제한인 100 이하여야 합니다.")
        max_retries = _positive_int("KSTARTUP_MAX_RETRIES", 3)
        timeout_seconds = _positive_float("KSTARTUP_REQUEST_TIMEOUT_SECONDS", 30.0)
        persistence = os.getenv("GRANT_RADAR_PERSISTENCE", "local").strip().lower()
        if persistence not in {"local", "hybrid"}:
            raise ConfigurationError("GRANT_RADAR_PERSISTENCE는 local 또는 hybrid여야 합니다.")
        database_url = _optional_env("DATABASE_URL")
        s3_endpoint_url = _optional_env("S3_ENDPOINT_URL")
        s3_access_key_id = _optional_env("S3_ACCESS_KEY_ID")
        s3_secret_access_key = _optional_env("S3_SECRET_ACCESS_KEY")
        s3_bucket_raw = _optional_env("S3_BUCKET_RAW")
        s3_bucket_processed = _optional_env("S3_BUCKET_PROCESSED")
        if persistence == "hybrid":
            missing = [
                name
                for name, value in {
                    "DATABASE_URL": database_url,
                    "S3_ENDPOINT_URL": s3_endpoint_url,
                    "S3_ACCESS_KEY_ID": s3_access_key_id,
                    "S3_SECRET_ACCESS_KEY": s3_secret_access_key,
                    "S3_BUCKET_RAW": s3_bucket_raw,
                    "S3_BUCKET_PROCESSED": s3_bucket_processed,
                }.items()
                if not value
            ]
            if missing:
                raise ConfigurationError(f"hybrid 저장에는 {', '.join(missing)} 환경변수가 필요합니다.")

        return cls(
            api_url=api_url,
            api_key=api_key,
            page_size=page_size,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            data_dir=Path(os.getenv("GRANT_RADAR_DATA_DIR", "data")),
            persistence=persistence,
            database_url=database_url,
            s3_endpoint_url=s3_endpoint_url,
            s3_access_key_id=s3_access_key_id,
            s3_secret_access_key=s3_secret_access_key,
            s3_bucket_raw=s3_bucket_raw,
            s3_bucket_processed=s3_bucket_processed,
        )


def _load_dotenv(path: Path) -> None:
    """외부 의존성 없이 로컬 개발용 .env의 단순 KEY=VALUE 형식을 읽습니다."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        # CI나 셸에서 명시한 값이 .env보다 우선합니다.
        if key:
            os.environ.setdefault(key, value)


def _positive_int(name: str, default: int) -> int:
    """환경변수를 양의 정수로 읽고 잘못된 설정을 조기에 차단합니다."""
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise ConfigurationError(f"{name}은 정수여야 합니다.") from error
    if value <= 0:
        raise ConfigurationError(f"{name}은 0보다 커야 합니다.")
    return value


def _positive_float(name: str, default: float) -> float:
    """환경변수를 양의 실수로 읽고 잘못된 설정을 조기에 차단합니다."""
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as error:
        raise ConfigurationError(f"{name}은 숫자여야 합니다.") from error
    if value <= 0:
        raise ConfigurationError(f"{name}은 0보다 커야 합니다.")
    return value


def _optional_env(name: str) -> str | None:
    """빈 문자열은 설정하지 않은 값으로 취급해 검증 분기를 단순하게 유지합니다."""
    value = os.getenv(name, "").strip()
    return value or None
