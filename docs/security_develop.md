# 플러그인 보안 강화 — 이슈/계획 메모 (구현 안 됨, 코드 미반영)

## 0. 문서 목적 및 현재 상태

이 문서는 **구현 계획이 아니라 메모**다. 2026-09-17, 사용자가 "비공식 zip 배포 플러그인이 꽤 있고, 장기적으로 악의적인 플러그인에 대비해야 한다"고 판단해 대응 방향을 논의했고, "지금 소스에 티를 내고 싶지 않다, 기능이 안정화되면 조금씩 반영하자"는 방침에 따라 **코드는 한 줄도 바꾸지 않고** 이슈/계획만 기록해 둔다. 다음에 실제로 착수할 때는 아래 내용을 출발점으로 삼되, 인용된 파일/라인이 여전히 유효한지 먼저 확인할 것.

관련 결정: 유료/비공개 플러그인은 애초에 지원하지 않기로 했다(별도 메모리 `feedback_no_paid_closed_source_plugins_policy` 참고) — 이 문서는 "악의적 플러그인" 대응이지 "유료화 금지"와는 별개 주제다.

## 1. 배경 — 위협 모델

- BookOasis 플러그인은 `plugins/metadata/<id>/` 아래 Python 코드로, 코어와 **같은 프로세스에서 동적 import**되어 실행된다(`services/metadata_factory.py::_import_provider_module_and_class`). 즉 설치된 순간부터 사실상 코어와 동일한 권한(파일시스템, DB, 네트워크, 환경변수)을 가진 코드다 — 별도 프로세스/컨테이너 격리는 없다.
- 플러그인 배포 경로가 두 갈래다: (1) `sample_plugins/`처럼 코어 저장소에 병합되는 공식 경로, (2) 사용자들끼리 zip 파일로 주고받는 비공식 경로. (2)는 리뷰 과정이 전혀 없다.
- 셀프호스팅 소프트웨어라 관리자 본인이 이미 서버 root를 쥐고 있다는 점에서, "완전한 샌드박싱으로 모든 공격을 막는다"는 목표는 투자 대비 효율이 낮다. 현실적인 위협은 "관리자가 신뢰해서 설치한 플러그인이 **나중 업데이트에서** 악성화되는" 공급망형 시나리오에 가깝다(npm/PyPI 패키지 공급망 공격과 같은 구도).

## 2. 이미 있는 방어 장치 (2026-09-17 기준 현황)

- **`services/metadata_factory.py:48-134`**: 플러그인 소스에 대한 AST 기반 정적 검사. `subprocess` import, `os.system`/`os.popen`/`exec*`/`spawn*` 계열 호출, `__import__('subprocess')`를 탐지해 기본값으로는 `SecurityError`로 로드 자체를 차단한다. `ALLOW_PLUGIN_SUBPROCESS=true`(env)로 우회 가능하지만, 그 경우도 `logs/plugin_subprocess_allowed.log`에 어떤 플러그인이 어떤 호출을 썼는지 조용히 기록된다(대시보드 등 UI 노출 없음 — 관리자가 나중에 조사할 수 있게만).
- 이 검사는 **`_import_provider_module_and_class`가 호출될 때마다** 실행된다 — 즉 매 프로세스 시작 시 플러그인이 처음 로드되는 시점마다 다시 돈다. 코드 자체 주석에 한계가 명시돼 있다: 문자열 조합(`importlib.import_module('sub'+'process')`), `getattr(os, 'sy'+'stem')`, ctypes 직접 시스템콜, base64 인코딩 후 `exec()`하는 식의 "작정한 우회"는 탐지하지 못한다 — 부주의한 사용을 막는 용도이지 샌드박스가 아니라고 스스로 밝히고 있다.
- **`admin_only` 플러그인 매니페스트 규약**(v2.6.4, CHANGELOG 참고): 선언하면 대시보드/홈 위젯/카테고리 탭/사이드바/컨텍스트 메뉴 등 모든 contract가 비관리자에게 fail-closed로 차단됨. 다만 플러그인 스스로 선언하는 값이라 신뢰 기반이다 — 강제 검증 장치는 아니다.
- **`services/ssrf_guard.py`**: 플러그인이 코어가 제공하는 웹뷰/프록시 헬퍼(`window.BookOasisPlugin.getProxyUrl()` 등, `guide_plugins.md` §10)를 통해 외부 도메인에 접근할 때, 사설/루프백/링크로컬 IP 차단 + 리다이렉트 매 hop 재검증을 수행한다. **단, 이건 플러그인이 이 헬퍼를 "직접 쓸 때만" 적용된다** — 플러그인 코드가 `requests`/`urllib`/소켓을 자체적으로 import해서 바로 호출하면 이 가드를 완전히 우회한다.
- **`repositories/*_repository.py` + `get_db_gateway()` 추상화**: 정상적인 플러그인은 이 게이트웨이를 통해서만 DB에 접근하도록 설계돼 있지만, Python이라 강제할 방법이 없다 — 플러그인이 `sqlite3`/`pymysql`을 직접 import해서 우회하는 것을 막는 장치는 없다.
- **[[project_mcp_tier_b_approval_queue]]** (2026-09-15, MCP 서버 대량 쓰기): "AI/자동화가 제안만 만들고, 관리자가 변경 전/후를 검토한 뒤 승인해야 실제 반영"되는 큐 패턴이 이미 구축·검증돼 있다. 아래 3-2 계획이 그대로 재사용하려는 게 이 패턴이다.

## 3. 이슈 — 지금 못 잡는 것들

1. 네트워크 유출: 플러그인이 `requests`/`urllib.request`/`socket`을 직접 써서 임의 외부 서버로 DB 내용이나 파일을 전송해도 탐지/차단 안 됨(ssrf_guard는 opt-in 헬퍼 경로에만 적용).
2. DB 우회 접근: `get_db_gateway()`를 거치지 않고 raw `sqlite3`/`pymysql` 커넥션을 직접 여는 것을 막는 장치 없음.
3. 코드 실행/역직렬화: `eval`/`exec`/`pickle.loads`/`ctypes` 사용에 대한 탐지 없음.
4. **업데이트 시점 재검토 부재로 추정됨(코드로 재확인 필요)**: 정적 검사가 "모듈 최초 import 시점"마다 실행되는 건 확인했지만, "설치된 플러그인이 샘플 업데이트(`/api/media/metadata/plugins/sample-update`)로 코드가 바뀌는 시점에 관리자가 diff/스캔 결과를 사전에 보고 승인하는" 흐름은 없어 보인다 — 서버가 재시작되면서 새 버전이 조용히 import될 뿐, "이 업데이트에 새로 추가된 위험 패턴"을 관리자에게 알리는 절차가 없다. 이게 공급망 공격 시나리오에서 가장 취약한 지점이다.
5. 정적 검사 자체의 근본 한계(이미 문서화돼 있고 해결 불가 영역): 난독화/문자열 조합 우회는 AST 매칭으로 못 잡는다. 이건 "왜 이 방식으로 전체를 막을 수 없는가"의 근거이지, 추가로 고쳐야 할 버그가 아니다.

## 4. 구현 계획 (단계별, 착수 시 이 순서로)

### 4-1. 기존 스캐너 검사 항목 확장 (가장 싸고 빠름)
`_find_forbidden_calls_in_source`(`services/metadata_factory.py`)에 검사 패턴 추가, 같은 "기본 차단 + `ALLOW_PLUGIN_*` 계열 env로 opt-in 우회 + 로그만 기록" 패턴을 그대로 재사용:
- 직접 소켓/`requests`/`urllib.request` import
- raw `sqlite3`/`pymysql` import (플러그인 코드에서 — `database.py`/`repositories/` 자체는 검사 대상 아님)
- `eval`/`exec`/`pickle.loads`/`ctypes`

주의: subprocess 케이스와 달리 `requests`/`sqlite3` 등은 정상적인 플러그인도 쓸 수 있는 흔한 모듈이라(예: 외부 API 호출), 무조건 차단이 아니라 "감지 시 경고 로그 + 관리자 대시보드에 노출" 쪽이 더 맞을 수 있음 — 착수 시 재검토.

**오픈소스 연동 후보 (2026-09-17 추가 검토)**: 검사 항목을 하나씩 손으로 늘리는 대신 기존 도구를 붙이는 게 유지보수 부담이 훨씬 적을 수 있다.
- **[Bandit](https://github.com/PyCQA/bandit)** (PyCQA, Apache-2.0): 지금 `_find_forbidden_calls_in_source`가 하려는 일(위험 패턴 AST 검사)을 이미 폭넓게, 검증된 룰셋으로 제공한다 — `eval`/`exec`, `pickle.loads`, `subprocess`/`os.system`, 하드코딩 시크릿, 안전하지 않은 `yaml.load`, `tarfile` 경로 순회 등. 순수 Python 의존성이라 무겁지 않고 라이선스도 AGPL과 충돌 없음. 4-1을 "직접 검사 항목 추가"가 아니라 "Bandit 실행 + 결과 룰ID별로 차단/경고 등급 매핑"으로 바꾸는 방향 검토.
- **[pip-audit](https://github.com/pypa/pip-audit)** (PyPA 공식, Apache-2.0): `ensure_plugin_dependencies()`(`metadata_factory.py:281`)가 설치하는 플러그인별 pip 의존성 자체에 알려진 CVE가 있는지는 지금 전혀 검사하지 않는다 — 이 문서 3번(이슈) 목록에 없던 별개의 위협이라 추가로 적어둠. PyPI Advisory DB 대조라 설치 시점에 바로 돌릴 수 있다.

### 4-2. 설치뿐 아니라 업데이트 시점에도 검사 + 관리자 승인 게이트 (가장 중요)
`[[project_mcp_tier_b_approval_queue]]`의 "제안 → 관리자 승인" 구조를 재사용:
- 샘플 업데이트/외부 소스 업데이트 적용 전에 새 버전 소스에 대해 4-1의 스캔을 실행
- 스캔 결과(+ 가능하면 이전 버전과의 diff)를 관리자에게 보여주고 명시적 승인을 받은 뒤에만 실제 파일을 교체
- 이 흐름이 없으면 4-1을 아무리 정교하게 만들어도 "조용히 업데이트되고 다음 재시작에 새 코드가 그냥 로드"되는 구조는 그대로 남는다.

### 4-3. 완전한 프로세스/컨테이너 샌드박싱 (보류)
셀프호스팅 특성상(관리자가 이미 root) 투자 대비 효율이 낮다고 판단, 4-1/4-2로 못 막는 실제 사고가 한 번이라도 발생하면 그때 재검토.

## 5. 앞으로 해야 할 것 (다음 착수 시 체크리스트)

- [ ] 4-1 착수 전, 이 문서의 파일/라인 인용이 여전히 유효한지 `services/metadata_factory.py` 재확인
- [ ] 4-1의 `requests`/`sqlite3` 탐지가 오탐(정상 플러그인 차단)을 얼마나 낼지 기존 `sample_plugins/`/커뮤니티 플러그인 전수 스캔으로 먼저 가늠
- [ ] 4-2 착수 전, "샘플 업데이트/외부 소스 업데이트" 실제 코드 경로(`/api/media/metadata/plugins/sample-update` 핸들러) 다시 추적해서 지금 정말 사전 승인 없이 바로 적용되는지 확인
- [ ] 이 모든 게 "기능이 안정화된 뒤"라는 사용자 방침에 따라, 플러그인 생태계/코어 기능이 큰 변화 없이 안정된 시점에 다시 꺼낼 것 — 지금은 메모만
