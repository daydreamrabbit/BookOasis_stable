---
title: "MCP 서버 가이드"
project: "BookOasis"
category: "guide"
date: 2026-09-14
tags: [mcp, ai, claude, guide]
---

# 🤖 BookOasis MCP 서버 가이드

서재 규모가 커질수록(수만~수십만 권) 데이터 품질(빠진 표지·장르·태그, 흩어진 중복 시리즈 등)을 손으로 훑어보기가 사실상 불가능해집니다. BookOasis는 이를 위해 **읽기 전용 MCP(Model Context Protocol) 서버**를 내장하고 있어, MCP를 지원하는 AI 코딩 도구(Claude Code, Claude Desktop, Gemini CLI, OpenAI Codex CLI, Cursor 등 — MCP는 특정 회사 전용이 아닌 공개 표준입니다)라면 어떤 걸 쓰든 서재 데이터를 직접 조회하고 문제를 찾아 관리자에게 알려주게 할 수 있습니다.

- 전송 방식은 **로컬 stdio 전용**입니다 — 네트워크로 노출되지 않으며, BookOasis가 설치된 바로 그 서버에서 AI 도구가 `tools/mcp_server.py` 프로세스를 직접 실행해서 붙습니다. 별도 인증 설정이 필요 없습니다.
- v1은 **읽기 전용**입니다. 검색·통계·데이터품질 진단만 제공하며, 실제 수정은 여전히 관리자가 기존 웹 UI에서 직접 합니다.
- 먼저 `pip install -r requirements.txt`로 `mcp` 패키지를 설치해야 합니다. 아래는 각 클라이언트별 등록 방법입니다 — 안 쓰는 도구는 건너뛰세요.

## 등록 방법

### 공통 — MCP 서버 정의 (JSON)

거의 모든 MCP 클라이언트는 결국 아래와 같은 형태의 JSON 블록으로 "이 명령을 실행하면 붙일 수 있는 stdio MCP 서버가 있다"를 등록합니다. 클라이언트마다 이 블록을 넣는 설정 파일 위치/이름만 다릅니다.

```json
{
  "mcpServers": {
    "bookoasis": {
      "command": "python3",
      "args": ["/path/to/media_server/tools/mcp_server.py"]
    }
  }
}
```

`/path/to/media_server`는 실제 BookOasis 설치 경로(절대경로)로 바꾸세요.

### Claude Code

```bash
claude mcp add bookoasis -- python3 /path/to/media_server/tools/mcp_server.py
```

등록 후 `claude mcp list`로 `✔ Connected`가 뜨는지 확인하세요.

### Claude Desktop

`claude_desktop_config.json`(macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`)을 열어 위 "공통 JSON" 블록을 `mcpServers` 항목에 추가하고 앱을 재시작하세요.

### Gemini CLI / OpenAI Codex CLI / Cursor 등 기타 MCP 클라이언트

이들도 대부분 위와 동일한 `mcpServers` JSON 형태를 쓰지만, 설정 파일 이름·위치와 CLI 등록 명령(있다면)은 도구마다 다르고 계속 바뀔 수 있습니다. 각 도구의 최신 공식 문서에서 "MCP server 등록"을 찾아 위 공통 JSON 블록을 그대로 붙여넣으면 됩니다 — `command`/`args`만 맞으면 어떤 클라이언트든 동일하게 동작합니다.

개발 중 클라이언트 없이 툴 목록/스키마만 빠르게 확인하려면(공식 `mcp` 패키지 제공 인스펙터):

```bash
mcp dev tools/mcp_server.py
```

## 제공 툴 (v1, 읽기 전용)

| 툴 | 설명 |
| :--- | :--- |
| `search_books` | 제목/시리즈명으로 시리즈 검색 (장르/태그 필터 지원) |
| `get_library_stats` | 전체 및 카테고리별 시리즈 수·도서 권수 통계 |
| `find_missing_cover` | 표지 이미지가 없는 도서 목록 |
| `find_missing_genre_and_tags` | 장르·태그가 모두 비어있는 도서 목록 |
| `find_missing_offsets` | 페이지 오프셋 캐시가 없어 재스캔이 필요한 zip/cbz 도서 목록 (rclone/GDrive 등 원격 마운트 파일은 자동 제외) |
| `find_duplicate_series` | 동일한 시리즈명이 서로 다른 카테고리 2곳 이상에 흩어진 케이스 |
| `run_readonly_query` | 서재 DB에 읽기 전용(SELECT/WITH/EXPLAIN/PRAGMA) SQL을 직접 실행 |
| `read_logs` | `logs/` 폴더의 서버 로그를 끝에서부터 최근 N줄 조회 (검색어 필터 지원) |

`find_duplicate_series`는 정확히 같은 시리즈명만 잡습니다. 오타나 표기가 다른 유사 시리즈명까지 찾으려면 `search_books`로 Claude가 직접 탐색·판단하게 하는 편이 낫습니다 — 이런 퍼지 매칭 판단이야말로 MCP로 AI에게 맡기는 이유입니다.

### `run_readonly_query` — 스키마를 모르면 먼저 물어보세요

미리 만들어진 진단 툴로 커버되지 않는 새 조건은 이 툴로 즉석에서 조회하면 됩니다. 테이블 구조가 궁금하면 먼저 `PRAGMA table_info(books)` 같은 스키마 조회부터 해보세요. 안전장치는 2단계입니다:

1. **앱 레벨**: SQL이 `SELECT`/`WITH`/`EXPLAIN`/`PRAGMA`로 시작하지 않거나, 세미콜론으로 여러 구문이 붙어있거나, `INSERT`/`UPDATE`/`DELETE`/`DROP` 등 쓰기 키워드가 포함되면 즉시 거부됩니다.
2. **DB 레벨(진짜 안전판)**: sqlite 모드는 매번 별도의 OS 레벨 읽기전용 커넥션(`file:...?mode=ro`)을 열어 실행합니다 — 1번 검증이 뚫려도 파일에 물리적으로 쓸 수 없습니다. MariaDB 모드는 읽기전용 계정이 따로 없어서, 커넥션을 빌린 동안만 `SET SESSION TRANSACTION READ ONLY`를 걸어 서버가 쓰기를 거부하게 만들고 끝나면 원복합니다(MariaDB 쪽이 sqlite보다 방어가 한 단계 약합니다 — 읽기전용 계정을 별도로 만들 계획은 없습니다, 어차피 신뢰된 운영자 1인 전용 로컬 stdio 서버라서요).

## db_type 값

대부분의 툴은 `db_type` 파라미터를 받습니다: `general`(일반 도서, 기본값) / `adult`(성인 서재) / `audiobook`(오디오북). `video`는 book 테이블 구조가 달라 진단 전용 툴(`find_missing_*`, `find_duplicate_series`)의 대상은 아니지만, `run_readonly_query`는 `video`도 허용합니다.

## 향후 계획

- 쓰기 툴(일괄 장르/태그 수정, 재스캔 트리거) — 진단 툴로 신뢰를 확인한 뒤 검토. 파괴적 작업은 즉시 실행이 아니라 "변경안 제시 → 관리자가 웹 UI에서 승인" 형태를 우선 검토합니다.
- 고아 파일(DB엔 있는데 디스크엔 없는 파일) 감지 — 원격 마운트 환경에서 전수 디스크 I/O가 느려서, 기존 스캐너 큐를 재사용하는 백그라운드 작업 + 결과 조회 전용 툴로 별도 추진합니다.
