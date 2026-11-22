# 최종 등록 자료 작동·성능 확인 (2026-11-11 12시)

제출 휴대용 zip(hwpai-portable-win64.zip)을 새 폴더에 풀어, 그 안의 코드로 모든 하위 명령을 실제로 돌렸다(Linux, 시스템 Python 3.13·Node 22 — 동봉된 Windows용 python·node 대신). 사람 손을 대지 않는 스크립트로 돌렸고, 외부 모델은 기기 안 가짜 OpenAI 호환 서버로 HTTP 왕복까지 확인했다.

## 명령별 결과 — 통과 35/35

| 명령 | 결과 | 확인한 것 |
|---|---|---|
| doctor | 통과 | 결론: 사용할 수 있습니다 |
| engines | 통과 | 자가 점검: 엔진 rhwp-wasm 0.9.0-local.c100 · HWP 생성→HWPX 변환 35.4ms · 검증서 PASS |
| read | 통과 | 글자 186 |
| convert | 통과 | PASS 4/4, 이관대장 csv·xlsx·jsonl True |
| convert 이어하기 | 통과 | 재실행 정상 |
| drop | 통과 | True 결과 폴더 |
| audit | 통과 | PASS |
| hwpxcheck | 통과 | 구조 오류 0 |
| export | 통과 | 파일 12개 |
| export --ai-folder | 통과 | 확인 필요 문서는 AI 폴더에서 빠짐: True |
| meta | 통과 | JSON 출력 정상 |
| meta --scrub | 통과 | 속성 비운 새 파일 True |
| aicheck | 통과 | 저장: 〈작업폴더〉/conv/AI친화도_점검.md / .json / .html |
| visual | 통과 | 보고서 True |
| replace | 통과 | 새 파일 True |
| replace(자리표시 만들기) | 통과 | JSON 출력 정상 |
| fill | 통과 | 채움 ['대상시기'] · 되읽기 검증 True · 나머지 글·표·그림 같음 True |
| fill(없는 키 → 알림) | 통과 | 없는 칸을 missing 으로 알림 |
| check | 통과 | 결과: 〈작업폴더〉/chk/AI투입점검.xlsx |
| corpus | 통과 | 조각 파일 True |
| cert | 통과 | [PASS] 보존 증명서: 〈작업폴더〉/cert/sample_plan_보존증명서.md |
| review make | 통과 |     1  [휴대전화] 010-0000-0000  (1회)  …이트 시험용 모의 문서  담당자 휴대전화: 010-0000-0000  이 문서는 개인정… |
| sens scan | 통과 | 확인 필요 표시 |
| sens review | 통과 | 검토 화면 True |
| watch(2회) | 통과 | 변환본 1 |
| scan-all 미리보기 | 통과 | 미리보기만 했습니다. |
| install(기본: 아무것도 안 함) | 통과 | 켜려면: python -m hwpai install --scan-all  (동의 확인 후 설정에 기록, 변환은 하지 않음) |
| ctxmenu(.reg 만들기만) | 통과 | .reg 2 |
| mcp-install --print | 통과 | JSON 출력 정상 |
| mcp-setup status | 통과 | chatgpt: 설정 파일 없음 (시험용 빈 홈 폴더)|
| ask(확인 전 문서 → 확인 요청으로 멈춤) | 통과 | 확인 요청 안내: True |
| ask(공개 지정, 모델 2개) | 통과 | 답 2개 True · 일치 판정 True |
| mcp(JSON-RPC) | 통과 | 도구 8개 · read_hwp True · get_tables True · convert 1건 · 확인 전 문서 막힘 True |
| gui(127.0.0.1 화면) | 통과 | 화면 응답 |
| 단위 시험(tests) | 통과 | Ran 19 tests in 0.759s OK |

## 성능(제출 코드)

| 시험 | 결과 |
|---|---|
| 공개 보도자료 1,000건 일괄 변환·검증(2코어 클라우드, 동시 2) | 1,000/1,000 변환, PASS 999·FAIL 1(0195, 보수 판정), 102초(1건 변환 중앙값 27ms), 민감정보 확인 필요 266건 — 이전 기록과 판정 같음 |
| 공개 저장소 2,333건 회귀(C121) | 판정·집계 변화 0 (PASS 2,244·WARN 44·FAIL 1, HWP 아닌 44건 제외) |
| 한글 2024 실기 2,286건 | 모두 열림, 쪽 수 2,234/2,234 |

## 웹판·휴대폰 앱

| 시험 | 결과 |
|---|---|
| 휴대폰(Pixel 7 에뮬레이션)·로컬 서버 | 설치 조건 오류 0, 오프라인 캐시 25개 파일, 표본 4건 변환·zip → 인터넷 끊고 다시 열어 4건 변환·zip, 외부 요청 0 |
| 파일로 열기(file://) | 하위 폴더 3건 PASS, 외부 요청 0, 한글 파일 이름(NFD→NFC)·시간 한도·손상 파일 격리 정상 |
| 데스크톱판과 공통 모듈 | 웹판 파이썬 모듈 19개 모두 데스크톱판과 바이트 단위로 같음 |

## 이번 확인에서 고친 것

- corpus 명령에 폴더를 넣으면 멈추던 문제(IsADirectoryError) → 하위 폴더까지 문서마다 조각을 만들도록 고침.
- 1,000건 처리 시간: 문서에 남아 있던 옛 코드 측정값(48초)을 제출 코드 재측정값(102초, 2코어)으로 바꿈.

## 시험하지 못한 것

- Windows 실기에서 이 판의 zip 을 다시 풀어 돌리지는 않았다(이전 판은 사용자 PC에서 check.bat·끌어놓기 확인). 실제 휴대폰 기기·iOS 사파리.
