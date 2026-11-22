# Windows 실기 확인 (2026-11-11 13:20, 사용자 Windows PC)

제출 릴리스 zip(hwpai-portable-win64.zip, SHA-256 dee146f89605b3fc…)을 Windows 압축 풀기로 새 폴더에 풀고, 동봉된 python\python.exe·node\node.exe 로 README 에 적힌 실행 방법을 그대로 돌렸다(hwpai.bat·check.bat·hwpai_open.bat·hwpai_ai_connect.bat 포함).

- 결과: **48/48 통과** (하위 명령 35개 · bat 실행 12개 · 단위 시험 19개 묶음)
- 성능(같은 PC, 1차 실행): 정부 공개 HWP 1,000건 변환·검증 245초(동시 2), PASS 999 · FAIL 1(0195) — 리눅스 결과와 판정 같음
- 확인 중 찾아 고친 것: ① `hwpai.bat ctxmenu` 가 `--root` 없이 멈춤 → 휴대용 폴더를 자동으로 씀 ② 화면 기본 번호(8765)를 다른 프로그램이 쓰고 있으면 `hwpai.bat` 더블클릭 화면이 열리지 않음 → 빈 번호로 연다. 두 수정 뒤 다시 풀어 48/48.
- 열리는 창(README 동작): 끌어놓기 뒤 결과 폴더·요약, hwpai_open.bat 의 한글 열기, 더블클릭 시 브라우저 화면 — 실제로 열림을 확인.

## 항목별 결과

통과 48/48

| 명령 | 결과 | 초 | 확인한 것 |
|---|---|---|---|
| doctor | 통과 | 3.5 | 결론: 사용할 수 있습니다 |
| engines | 통과 | 1.0 | 자가 점검: 엔진 rhwp-wasm 0.9.0-local.c100 · HWP 생성→HWPX 변환 49.1ms · 검증서 PASS |
| read | 통과 | 0.4 | 글자 168 |
| convert | 통과 | 1.5 | PASS 4/4, 이관대장 csv·xlsx·jsonl True |
| convert 이어하기 | 통과 | 0.6 | 재실행 정상 |
| drop | 통과 | 1.9 | True 결과 폴더 |
| audit | 통과 | 0.6 | PASS |
| hwpxcheck | 통과 | 0 | 구조 오류 0 |
| export | 통과 | 1.0 | 파일 12개 |
| export --ai-folder | 통과 | 0.4 | 확인 필요 문서는 AI 폴더에서 빠짐: True |
| meta | 통과 | 0.2 | JSON 출력 정상 |
| meta --scrub | 통과 | 0.3 | 속성 비운 새 파일 True |
| aicheck | 통과 | 0.3 | 저장: 〈작업폴더〉\conv\AI친화도_점검.md / .json / .html |
| visual | 통과 | 1.2 | 보고서 True |
| replace | 통과 | 0.6 | 새 파일 True |
| replace(자리표시 만들기) | 통과 | 0.5 | JSON 출력 정상 |
| fill | 통과 | 1.0 | 채움 ['대상시기'] · 되읽기 검증 True · 나머지 글·표·그림 같음 True |
| fill(없는 키 → 알림) | 통과 | 0.8 | 없는 칸을 missing 으로 알림 |
| check | 통과 | 0.4 | 결과: 〈작업폴더〉\chk\AI투입점검.xlsx |
| corpus | 통과 | 0.4 | 조각 파일 True |
| cert | 통과 | 0.4 | [PASS] 보존 증명서: 〈작업폴더〉\cert\sample_plan_보존증명서.md |
| review make | 통과 | 0.3 |     1  [휴대전화] 010-0000-0000  (1회)  …이트 시험용 모의 문서  담당자 휴대전화: 010-0000-0000  이 문서는 개인정… |
| sens scan | 통과 | 0.3 | 확인 필요 표시 |
| sens review | 통과 | 0.3 | 검토 화면 True |
| watch(2회) | 통과 | 1.9 | 변환본 1 |
| scan-all 미리보기 | 통과 | 0.3 | 미리보기만 했습니다. |
| install(기본: 아무것도 안 함) | 통과 | 0.3 | 켜려면: python -m hwpai install --scan-all  (동의 확인 후 설정에 기록, 변환은 하지 않음) |
| ctxmenu(.reg 만들기만) | 통과 | 0.2 | .reg 2 |
| mcp-install --print | 통과 | 0.2 | JSON 출력 정상 |
| mcp-setup status | 통과 | 0.2 | chatgpt: 등록 안 됨 (이 PC 설정 읽기만) |
| ask(확인 전 문서 → 확인 요청으로 멈춤) | 통과 | 0.4 | 확인 요청 안내: True |
| ask(공개 지정, 모델 2개) | 통과 | 0.4 | 답 2개 True · 일치 판정 True |
| mcp(JSON-RPC) | 통과 | 0 | 도구 8개 · read_hwp True · get_tables True · convert 1건 · 확인 전 문서 막힘 True |
| gui(127.0.0.1 화면) | 통과 | 0 | 화면 응답 |
| 단위 시험(tests) | 통과 | 0 | Ran 19 tests in 1.792s OK |
| check.bat(설치 점검) | 통과 | 1.2 | 결론: 사용할 수 있습니다 |
| hwpai.bat doctor | 통과 | 1.1 | 결론 정상 |
| hwpai.bat convert | 통과 | 1.2 | PASS 4/4 |
| hwpai.bat 아이콘에 폴더 끌어놓기 | 통과 | 1.8 | 결과 폴더 True · PASS 4 |
| hwpai.bat read | 통과 | 0.9 | 본문 글자 168 |
| hwpai.bat audit | 통과 | 1.0 | PASS |
| hwpai.bat export | 통과 | 0.8 | 파일 12 |
| hwpai.bat sens review | 통과 | 0.3 | 검토 화면 True |
| hwpai.bat ask --grade 공개(모의 모델 2개) | 통과 | 0.5 | 8,500 답 3 |
| hwpai_open.bat(HWP 열기 → HWPX 로 열기) | 통과 | 1.2 | 변환본 1 |
| hwpai_ai_connect.bat(상태만 보고 취소) | 통과 | 0.5 | 상태 표시 True |
| hwpai.bat ctxmenu(.reg 만들기만) | 통과 | 0.4 | .reg 2 |
| hwpai.bat 더블클릭(화면) | 통과 | 2.5 | 브라우저 화면 응답 |
