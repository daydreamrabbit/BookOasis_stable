# Samsung ko_kr_l08 서버 실행 검증 — 미완료

요구사항: 지정 음성을 `여성 6`으로 추가하고, 서버에서 합성하여 브라우저의 합성 부하를 없앤다. 실제 발화, 읽기 위치 동기화, 취소, 과부하 제한 검증 전에는 운영 UI에서 활성화하지 않는다.

## 현재 환경과 실험

- 호스트: Linux x86_64. 제공 라이브러리: Android ARM32/ARM64.
- 임시 재현 프로젝트: `/tmp/bookoasis-samsung-probe-f466Yq` (`pom.xml`, `Dockerfile`, `src/main/java/Probe.java`).
- 테스트 이미지: `bookoasis-samsung-probe:local`. 운영 Compose 및 BookOasis 이미지는 변경하지 않았다.
- unidbg-android 0.9.8, unidbg-dynarmic 0.9.8, AndroidResolver(23).
- 원본 음성 폴더를 `/voice`에 읽기 전용 마운트. 네트워크 없음, 모든 capability 제거, 읽기 전용 루트, 비특권 UID, CPU 1개, 메모리 및 swap 합계 768MiB, PID 64, Java heap 384MiB, 실행 제한 30~45초.
- 원본 파일은 수정하지 않았다. 파일 접근 어댑터는 읽기 전용 ByteArrayFileIO로 처리한다. SimpleFileIO는 내부적으로 쓰기 모드로 열어 읽기 전용 마운트에서 실패했다.

## 확인된 결과

1. `loadLibrary(file, true)`로 생성자까지 실행해야 한다. 엔진 버전 조회값 `482310161`, 초기 로딩 약 1.2~1.8초.
2. `IENGINE_New` → `IEngine::SetVoice("/voice/")` → `IEngine::Initialize()` 호출로 cfg, lng, regular.ivc, cache.tsv 로딩 성공, 반환값 0. 파일 경로와 입력 문자열은 게스트의 별도 메모리에 유지했다.
3. 기본 실행 설정에서는 합성이 반환되지 않고 30초/45초 제한에 도달했다. 관측 CPU 약 한 코어, 메모리 약 378~441MiB. 이 수치는 샘플 시점 측정이며 최고 사용량 보장이 아니다.
4. `setEnableThreadDispatcher(true)` 이후 짧은 문장의 합성 호출이 반환됐다. 하지만 반환값 0만으로 발화 성공을 판단할 수 없다.
5. `안녕하세요.` 시험: sample rate 24000, generated PCM count 34880, 전체 실행 약 3.6초. 카운터 증가량만큼 버퍼 앞부분을 읽은 검사에서 nonzero byte가 349개뿐이었다. 버퍼/API 해석 및 실제 음성 파형은 아직 검증되지 않았다. **정상 음성 생성 성공으로 분류하지 않는다.**

## 남은 작업

- Samsung 합성 API/버퍼/콜백/스레드 호출 계약 확인. 가능하면 엔진 SDK/API 헤더 또는 MultiTTS의 정상 호출 구현 확보.
- 실제 한국어 WAV 생성 및 내용 검증. 메모리/CPU/실시간 대비 합성 속도 측정.
- 서버 작업자, 인증된 API, 제한된 큐/문장 길이/응답 크기, 취소 및 타임아웃, 재시도 제한, 캐시 상한 구현.
- `여성 6` 선택 시 브라우저 ONNX 로딩·추론을 하지 않도록 분리. 기존 음성으로 자동 대체하지 않는다.
- 실제 PC/모바일의 첫 재생 지연, 화면 반응, 읽기 위치, 일시정지/재개, 빠른 페이지 이동/음성 전환 테스트.

현재는 타당성 검증 단계이며 운영 배포 및 사용자 목표 완료가 아니다.
