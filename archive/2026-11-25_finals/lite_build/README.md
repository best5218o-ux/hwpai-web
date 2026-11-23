# 경량판 — Node.js 없이 같은 변환 엔진 실행 (결선 개선·보완, 2026-11-23)

기능은 그대로 두고 **내려받는 프로그램 크기만 줄인 개선**입니다. 새 기능은 없습니다.

| 항목 | 기존(v9 휴대용) | 경량판 |
|---|---|---|
| 내려받는 zip | 62.2MB | **36.3MB (−42%)** |
| 압축을 푼 크기 | 157MB | 89MB |
| 변환 엔진 실행기 | 동봉 Node.js | 동봉 파이썬 + wasmtime 51 |
| 변환 엔진 | rhwp(@rhwp/core) C102, 34.5MB | 같은 엔진 최적화본, 28.4MB |

## 무엇을 바꿨나
- `changed_source/engines/rhwp_py.py` (새 연결부): rhwp WASM 엔진을 Node.js 대신 파이썬 wasmtime 에서 돌린다. wasm-bindgen 연결 함수 중 변환에 실제로 쓰이는 것(externref 표 초기화, 문자열·숫자 변환, 오류 던지기, Date·getTimezoneOffset, Error·stack, console.error)만 구현하고, 그 밖의 기능을 부르면 즉시 오류로 끝내 조용히 틀린 결과를 내지 않는다. 기존 Node 일꾼(rhwp_worker.mjs)과 같은 JSON 한 줄 규약.
- `changed_source/engines/__init__.py`: 엔진 선택 순서에 `rhwp-py`(파이썬 실행기)를 먼저 둔다. 실패하면 기존 `rhwp-wasm`(Node)·`rhwp-cli` 로 넘어간다.
- `changed_source/doctor.py`·`visual.py`: 자가 점검·시각 비교가 파이썬 실행기를 쓰도록. 엔진 지문을 최적화본(`25e6c8dc…`)으로 갱신.
- 엔진 최적화: binaryen wasm-opt 132 `-Oz --strip-debug --strip-producers --enable-bulk-memory --enable-nontrapping-float-to-int --enable-sign-ext --enable-mutable-globals --enable-reference-types --enable-multivalue` (`-all` 은 Node 로딩이 깨져 쓰지 않음). 첫 실행 때 컴파일본을 `%LOCALAPPDATA%\hwpai\engine-cache` 에 저장(약 15초, 다음부터 바로).
- 오류 수정 3건(audit·edit·explain)은 `../source_v9` 와 같다(`../source_v9/결선보완_오류수정_기록.md` 17차).

## 실증
- **리눅스 1,000건**: 정부 HWP 1,000건을 기존 엔진과 최적화 엔진으로 각각 변환 → 1,000/1,000 동일. 엔진 단계 1,307건 차이 0.
- **Windows 1,000건**(사용자 PC, 설치된 Node.js 를 PATH 에서 숨김): 판정·점수 동일 999/1,000건. 남은 1건 `0a606aa5243d` 는 기존 Node 판끼리도 실행할 때마다 결과가 달라지는 문서(기존 v9 의 변경 추적 뒤처리 간헐 실패, 경량판과 무관 — 미해결). HWPX 바이트 차이는 차트 zip 항목의 시각 기록만 다름.
  - 시간: 기존 623.6초 · 경량 첫 실행 671.5초 · 컴파일본 저장 후 610.8초.
  - `tests/1000건_1차_결과.txt`(1차: Date 연결 누락으로 3건 실패 → 수정), `tests/이관대장_*_1000건.csv`(2차 결과 원장).
- **Windows 기능 실기 7항목 통과**(`tests/기능실기_결과.txt`): 자가 점검 · 화면 끌어놓기 · 폴더 감시 자동 변환 · AI 연결(MCP 도구 8개) · 시각 비교 · 끌어놓기 명령 · 이관대장 엔진 기록 `rhwp-py`.

## 받기
`release/hwpai-lite-win64.zip` — 풀고 `hwpai.bat` 실행. SHA256 은 `release/SHA256SUMS.txt`.
