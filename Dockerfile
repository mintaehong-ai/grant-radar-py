FROM python:3.12-slim

WORKDIR /app

# 패키지 메타데이터를 먼저 복사해 이미지 캐시를 최대한 활용합니다.
COPY pyproject.toml README.md ./
COPY src ./src

# 컨테이너 안에서도 grant-radar 명령어를 바로 사용할 수 있게 설치합니다.
RUN pip install --no-cache-dir -e .

CMD ["grant-radar", "--help"]
