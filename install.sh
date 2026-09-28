#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$PROJECT_DIR"

if ! command -v docker >/dev/null 2>&1; then
    echo "[BookOasis] Docker가 설치되어 있지 않습니다." >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "[BookOasis] Docker Compose 플러그인을 사용할 수 없습니다." >&2
    exit 1
fi

if [ ! -f .env ]; then
    cp .env.example .env
    echo "[BookOasis] .env.example을 복사해 .env를 생성했습니다."
fi

mkdir -p db covers cache plugins logs custom_fonts mariadb_data docker-entrypoint-initdb.d

docker compose config --quiet
docker compose up -d --build
docker compose ps

echo "[BookOasis] 실행 완료: http://localhost:5930"
