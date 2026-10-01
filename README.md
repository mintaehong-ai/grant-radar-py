# 놓치지마 (Grant Radar)

지원사업 공고의 원본과 수집 시점별 버전을 보존해 신규 등록과 변경을 추적하는 데이터 파이프라인입니다.

현재는 K-Startup과 기업마당 지원사업 공고 API 수집부터 구현합니다. API 원본은 수정하지 않고 그대로 보관하며,
후속 처리에서 사용하기 좋은 JSON Lines 스냅샷도 함께 생성합니다.

## 시작하기

Python 3.12 이상이 필요합니다.

```powershell
Copy-Item .env.example .env
# .env에 공공데이터포털에서 확인한 API URL과 인증키를 입력합니다.
python -m grant_radar collect kstartup
python -m grant_radar collect bizinfo
```

개발 설치를 사용하는 경우:

```powershell
python -m pip install -e .
grant-radar collect kstartup
grant-radar collect bizinfo
```

수집 결과는 기본적으로 `data/raw/<출처>/<수집일>/<실행 ID>/`와
`data/processed/<출처>/<수집일>/<실행 ID>/notices.jsonl`에 저장됩니다.

실제 API를 호출하지 않고 응답 파일을 검증할 수도 있습니다.

```powershell
python -m grant_radar parse-kstartup path/to/response.json
python -m grant_radar parse-bizinfo path/to/response.json
```

## 로컬 Docker 인프라

오픈소스로 공개했을 때 사용자가 PostgreSQL과 S3 호환 저장소를 직접 설치하지 않아도 되도록
Docker Compose로 로컬 개발 인프라를 제공합니다.

```powershell
docker compose up -d postgres localstack s3-init
```

서비스 접속 정보:

| 서비스 | 주소 | 기본 계정 |
|---|---|---|
| PostgreSQL | `localhost:5432` | `grant_radar / grant_radar_password` |
| Adminer | `http://localhost:8080` | PostgreSQL 접속값 입력 |
| LocalStack S3 | `http://localhost:4566` | `test / test` |

Adminer 접속값:

| 항목 | 값 |
|---|---|
| System | `PostgreSQL` |
| Server | `postgres` |
| Username | `grant_radar` |
| Password | `grant_radar_password` |
| Database | `grant_radar` |

기본 실행은 로컬 `data/` 디렉터리에 저장합니다. `GRANT_RADAR_PERSISTENCE=hybrid`로 실행하면
같은 수집 결과를 PostgreSQL과 LocalStack S3에도 함께 저장합니다. PostgreSQL에는 공고 현재 상태, 버전,
변경 이벤트, 수집 실행 이력을 저장하고, S3에는 API 응답 JSON, manifest, 정규화 JSONL 같은
파일 데이터를 저장합니다.

컨테이너 안에서 K-Startup 수집기를 실행하려면 `.env`에 `KSTARTUP_API_KEY`를 채운 뒤 아래 명령을 사용합니다.

```powershell
docker compose --profile collector run --rm collector
```

## 환경변수

| 이름 | 설명 | 기본값 |
|---|---|---|
| `KSTARTUP_API_URL` | K-Startup 지원사업 공고 요청 URL | 공식 URL 내장 |
| `KSTARTUP_API_KEY` | K-Startup 서비스 일반 인증키(Encoding 키도 그대로 사용 가능) | 필수 |
| `KSTARTUP_PAGE_SIZE` | 페이지당 수집 건수 | `100` |
| `KSTARTUP_REQUEST_TIMEOUT_SECONDS` | 요청 제한 시간 | `30` |
| `KSTARTUP_MAX_RETRIES` | 일시적 오류 재시도 횟수 | `3` |
| `BIZINFO_API_URL` | 기업마당 지원사업정보 API URL | 공식 URL 내장 |
| `BIZINFO_API_KEY` | 기업마당에서 발급받은 서비스 인증키 | 필수 |
| `BIZINFO_PAGE_SIZE` | 기업마당 페이지당 수집 건수 | `100` |
| `BIZINFO_REQUEST_TIMEOUT_SECONDS` | 기업마당 요청 제한 시간 | `30` |
| `BIZINFO_MAX_RETRIES` | 기업마당 일시적 오류 재시도 횟수 | `3` |
| `GRANT_RADAR_DATA_DIR` | 데이터 저장 위치 | `data` |
| `GRANT_RADAR_PERSISTENCE` | 저장 방식. `local` 또는 `hybrid` | `local` |
| `DATABASE_URL` | PostgreSQL 접속 URL | 로컬 Docker 기준값 |
| `S3_ENDPOINT_URL` | 로컬 S3 엔드포인트 | `http://localhost:4566` |
| `S3_BUCKET_RAW` | 원본 데이터 버킷 | `grant-radar-raw` |
| `S3_BUCKET_PROCESSED` | 가공 데이터 버킷 | `grant-radar-processed` |

루트의 `.env`는 실행 시 자동으로 읽으며, 이미 설정된 시스템 환경변수를 덮어쓰지 않습니다.
PowerShell에서 현재 프로세스에 직접 설정할 수도 있습니다.

```powershell
$env:KSTARTUP_API_KEY="K-Startup 서비스에서 발급받은 인증키"
```

대상은 공공데이터포털 데이터셋 `15125364`의 `getAnnouncementInformation01` 기능입니다.
API 제공처가 URL을 변경할 때만 `KSTARTUP_API_URL`을 별도로 설정하면 됩니다.
