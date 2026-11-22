# HWP AI 어댑터 - HWP를 AI가 바로 읽고 HWPX로 바꾸는 어댑터 — 구동 안내서

> 양식 2-1(구동 안내서)의 구분 순서를 따랐다. 화면에 나오는 글자는 「」로 적었다.
>
> **한눈에 보기** — 한글 프로그램 없이 HWP를 HWPX로 옮기고, 옮긴 결과가 원본과 같은지 파일마다 증명한다(검증서·이관대장). 변환본은 Markdown·JSON·RAG 조각으로 바로 AI에 넣는다.
>
> | 확인한 것 | 결과 |
> |---|---|
> | 한글 2024에서 열기(공개 저장소 문서 2,286건) | 변환본 2,286건 모두 열림 · 쪽 수 2,234/2,234 · 글 2,224/2,227 원본과 같음 · 한글이 원본을 못 여는 46건도 변환본은 열림 |
> | 공개 보도자료 1만여 건(60개 기관, 2013~2026) | 10,446건 재측정 PASS 10,437 · 이전보다 나빠진 문서 0 |
> | 같은 표본 438건, 같은 검증 규칙 | 판정 PASS hwpai 437 · 한글 2024 자체 변환 431 · kordoc 436 (전체 비교·장점: 저장소 `docs/benchmark.md` 성능 비교 평가서) |
> | 행정망 PC + 업무망 온AI | 변환 PASS → 3개 모델 질의(Solar Pro 4 · HCX-GOV-THINK-30B · K-EXAONE), 지어낸 답 0(Solar·HCX) |
> | 실행 | 행정망 PC·외부망 PC(Windows)에서 작동, 설치·관리자 권한·인터넷 불필요 |

## 실행 환경
| 항목 | 내용 |
|---|---|
| 운영체제 | Windows 10/11 64비트. 휴대용 폴더에 Python 3.12·Node.js 22가 들어 있어 설치·관리자 권한·인터넷 연결이 필요 없다(행정망 PC에서 그대로 실행). Linux(Python 3.10+·Node.js 18+)에서도 돈다. |
| 브라우저 | 기본 브라우저(Edge·Chrome). 화면은 이 컴퓨터 안(127.0.0.1)에서만 열린다. 끌어놓기가 안 되는 브라우저는 「폴더 선택」을 쓴다. |
| 권장 사양 | 저장 공간: 압축 푼 폴더 약 160MB(zip 약 62MB) + 결과 폴더(원본과 비슷한 크기). 메모리 4GB 이상(변환 일꾼 하나 최대 약 330MB, 동시 변환 수만큼). 속도(제출 코드 재측정 11-11, 동시 2): 공개 HWP 1,000개 변환·검증 Windows 사무용 PC 245초 · 리눅스 2코어 102초. |
| 필요 소프트웨어 | 없음. LLM 질의(선택)만 OpenAI 호환 API 주소가 필요하다. |

## 설치·실행 절차
1. **받기**: 공공 GitLab 저장소의 `hwpai-portable-win64.zip`(SHA256은 저장소 `SHA256SUMS.txt`). zip 하나로 끝난다.
2. **점검**: 아무 폴더에 풀고 `check.bat`을 두 번 누른다. 마지막 줄 「결론: 사용할 수 있습니다.」면 준비 끝. 「[실패]」면 그 아래 「해결:」을 따른다. 「PC 보호」 창이 뜨면 「추가 정보」 → 「실행」(서명 없는 실행 파일이라 뜬다).
3. **첫 실행(끌어놓기 한 번)**: 탐색기에서 `sample_data` 폴더를 `hwpai.bat` 아이콘 위에 놓는다. 끝나면 `sample_data_hwpx변환` 폴더와 `요약.md`가 열린다(변환본·`_검증서/`·`이관대장.xlsx`). 결과: 4건 모두 PASS, 번호가 든 시험 문서 1건은 「확인 필요」.
4. **화면으로 쓰기**: `hwpai.bat`을 두 번 누르면 브라우저에 「HWP AI 어댑터」가 열린다(검은 창은 닫지 않는다). 폴더(하위 폴더 포함)·파일 여러 개를 끌어놓기 → 목록(「HWP·HWPX n개 · 용량 · 하위 폴더 n개 · 건너뜀 n개」) → 「보안등급」(기본·공개 자료·엄격) → 「변환 시작」. 진행 막대·남은 시간·파일별 판정이 실시간으로 나오고, 끝나면 「결과 폴더 열기」·「이관대장 열기」·「FAIL만 보기」. 같은 폴더를 다시 넣으면 끝난 파일은 건너뛴다.
5. **명령으로 쓰기(심사·자동화)**:
   ```
   hwpai.bat doctor                                    설치 점검
   hwpai.bat convert D:\문서함                         일괄 변환 → D:\문서함_hwpx변환
   hwpai.bat drop D:\가 D:\나 D:\다.hwp                 끌어놓기와 같은 일괄 변환(여러 개)
   hwpai.bat ask 문서.hwp "질문" --profiles 모델.json   LLM 질의(아래 LLM 연결 설정)
   ```
6. **민감정보 확인 요청**: 변환·검증은 이 컴퓨터 안에서만 하므로 막지 않는다. 등급이 없는 문서에서 휴대전화·주민등록번호·외국인등록번호·계좌번호·이메일·여권번호 꼴, 「성명:」 표기, 문서 속성(작성자 등)이 나오면 이관대장에 「확인 필요」로 적고, 사람이 확인하기 전에는 AI(`ask`·MCP·`export --ai-folder`)에 보내지 않는다. 확인은 `hwpai.bat sens review 폴더`(검출 값을 문서 위치와 함께 색으로 보여 주는 화면)에서 「민감정보 아님/있음」을 고른다. 결정은 문서 해시로 저장된다. 등급은 기계가 정하지 않는다.

## LLM 연결 설정
- **역할**: LLM은 `ask`(문서에 질문)에만 쓴다. 변환·검증·이관대장은 LLM 없이 동작한다.
- **실제 구동한 모델**

| 경로 | 모델 | 결과 |
|---|---|---|
| 행정망 PC → 업무망 온AI(변환 결과 첨부, 2026-11-09) | FabriX Solar Pro 4 / CLOVA Studio for GOV HCX-GOV-THINK-30B | 8문항 7/8 · 8/8, 지어낸 답 0 |
| 같은 경로, 공고문 2건 30문항 | Solar Pro 4 / K-EXAONE | 28/30 · 25/30 |
| 외부망 공개 API(`ask`, 2026-11-10) | 업스테이지 Solar Pro 4(주최 지원 API) / 네이버 HyperCLOVA X HCX-005 | 같은 근거로 핵심 값 일치 |
| 상용 대화형 서비스 웹 화면(합성 문서 3건) | ChatGPT · Gemini · Claude | 각 3/3 |

  업무망 온AI 두 서비스는 외부 도구(MCP) 등록 기능이 없어 변환 결과를 첨부해 쓴다.
- **설정(파일 하나, 여러 모델)** — 실제로 돌린 설정이다. 열쇠는 파일에 쓰지 않고 환경변수(`set SOLAR_API_KEY=발급받은키`)로 넣는다.
  ```json
  {"profiles": {
    "solar-pro4": {"base_url": "https://api.upstage.ai/v1", "model": "solar-pro4", "api_key_env": "SOLAR_API_KEY"},
    "hcx-005": {"base_url": "https://clovastudio.stream.ntruss.com/v1/openai", "model": "HCX-005", "api_key_env": "CLOVA_API_KEY"}}}
  ```
  모델 하나만 쓸 때는 `HWPAI_LLM_BASE_URL`·`HWPAI_LLM_MODEL`·`HWPAI_LLM_API_KEY`를 정하고 `--profile env`. 교체는 `base_url`·`model`만 바꾼다(행안부 AI 공통기반 API 주소도 같은 칸). 심사위원 PC에서도 Solar Pro 4 키를 넣으면 `hwpai.bat ask sample_data\sample_plan.hwp "2분기 대상 부서 수와 처리 건수는?" --profiles 모델.json`이 그대로 재현된다.
- **출력**: 모델별 답과 근거 조각 번호, 모델 간 비교 한 줄. 문장이 달라도 핵심 값(숫자+단위·날짜·기관명)이 같으면 일치로 본다. 실제 출력: Solar 「2분기 대상 부서 수는 12개, 처리 건수는 8,500건입니다.」, HCX 「2분기에는 12개 부서에서 8,500건의 문서가 처리됩니다.」 → 「핵심 값 일치: 12개 부서 · 8,500건 (예)」. 값이 다르거나 근거 조각에 없는 값이 나오면 「사람 확인」을 붙인다.

## 모의데이터 안내
- 동봉 `sample_data/`: 엔진으로 만든 합성 HWP 4건(실제 기관 문서 아님). 폴더째 `hwpai.bat`이나 화면에 끌어놓는다.
  - `sample_plan.hwp`(업무추진계획, 표 3×3) · `sample_minutes.hwp`(회의결과, 표 3×2) · `sample_notice.hwp`(안내문): 개인정보 없음, PASS. `sample_plan.hwp`는 LLM 질의 예시 문서다.
  - `sample_pii_block_test.hwp`: 쓰지 않는 번호(010-0000-0000)를 넣은 문서. 변환·PASS가 되고 「확인 필요」로 남아 확인 전에는 AI에 보내지 않는다.
- 원본 보호: 원본은 읽기만 한다. 결과는 원본 폴더 밖 「〈폴더〉_hwpx변환」에 쓴다(시험: 원본 해시·수정 시각 불변).

## 기능 사용 순서
1. **폴더째 변환·판정**: 파일마다 HWPX와 검증서를 만들고 PASS·WARN·FAIL을 매긴다. 검증은 변환 엔진과 다른 hwpai 판독기로 원본을 직접 읽어 글·표 칸·그림·각주·수식을 대조한다.
2. **사람 확인**: 「FAIL만 보기」로 거르고 행을 누르면 「검증서」에 차이 위치(문단, 표 행·열, 그림)가 나온다. `이관대장.xlsx`의 「사람확인목록」 시트로 넘긴다(1,000건 시험에서 사람이 볼 문서는 1건).
![끌어놓기 화면 — 모의 문서 4개(하위 폴더 2개, HWP 아닌 파일 1개 건너뜀)를 놓고 변환을 마친 모습. 번호가 든 시험 문서도 변환하고 「민감정보 확인」으로 넘긴다](img/gui_drop_done.png)

3. **AI 활용**: `ask`로 문서에 질문(여러 모델 비교)하거나, `hwpai.bat mcp-install`로 Claude 데스크톱 등에 MCP 도구 8개(read_hwp·get_tables·search_chunks·convert_to_hwpx·audit·export_doc·replace_text·fill_form)를 등록한다. AI가 부르는 도구에도 같은 확인 요청이 걸리고, 등급은 사람이 만든 등급 파일(`HWPAI_GRADE_FILE`)에서만 읽는다. 문서 내용은 「데이터」로만 표시해 넘긴다(문서 속 지시문 실행 방지).

## 추가 기능 사용법
| 기능 | 명령 | 설명 |
|---|---|---|
| AI용 내보내기 | `hwpai.bat export 대상 --out 폴더 --formats md,json,chunks` | 화면 「Markdown·JSON 내보내기」, MCP `export_doc`. `--ai-folder`는 확인 끝난 문서만 쓴다. JSON에 표 칸 좌표·병합·그림 해시, AI용에서는 작성자 등 속성을 뺀다 |
| 서식 보존 치환·양식 채우기 | `hwpai.bat replace 문서.hwpx 바꿀글.json` · `fill` | 새 파일과 변경 보고서, 되읽어 확인, 원본 보존 |
| 보존 증명서 | `hwpai.bat cert 원본.hwp 변환.hwpx` | 원본·변환본 해시 + 줄 대조 + 판정 한 장 |
| 시각 비교 | `hwpai.bat visual 원본.hwp 변환.hwpx` | 쪽별 그림을 나란히, 쪽 수·글·그림 대조 |
| AI 친화도·속성 점검 | `aicheck` · `meta [--scrub]` | 병합 칸·설명 없는 그림 등 보고, 작성자 속성 비우기 |
| 첨부 전 자동 변환 | `watch 폴더` · `ctxmenu`(기본 꺼짐) | 새 HWP 자동 변환·검증, 탐색기 우클릭 메뉴(.reg 사람 적용) |
| 제자리 교체·원본 보관(옵션 — 화면·끌어놓기·감시는 기본 켜짐, 끄기: 화면 체크 해제 · `--no-settle`; 삭제 기한 기본 30일) | 화면 「변환」→「변환 뒤 제자리 교체」 · 「보관 원본 정리」 / `drop 폴더 --archive auto` / `watch 폴더 --archive auto --keep-days 90 [--auto-purge]` · `convert 폴더 --archive 보관폴더` · `purge 보관폴더 [--yes]` / 웹판 「폴더 열기(제자리 교체용)」 | PASS 문서만 원래 자리에 .hwpx, 원본 .hwp 는 보관 폴더(`auto` = 폴더 옆 〈폴더〉_원본보관)로 이동. 삭제 예정일은 보관대장.csv 에 기록, 삭제는 조건 확인 후에만(삭제기록.csv). 기본 꺼짐 |
| 구조 검사 | `python\python.exe -m hwpai.hwpxcheck 파일.hwpx` | 한글 없이 HWPX 필수 구조·참조·버전 점검 |
| 웹판 | https://best5218o-ux.github.io/hwpai-web/ 열기, 또는 `hwpai-web.zip`의 `index.html` | 브라우저 안에서만 변환·검증·확인·내보내기(파일은 서버로 안 감). 폴더 감시·MCP·질문 없음 |
| 휴대폰 앱(PWA) | 휴대폰 크롬으로 위 주소 → 「앱 설치」(아이폰: 공유 → 홈 화면에 추가) | 설치 후 인터넷 없이 변환(11-11 시험: 설치 오류 0, 오프라인 4건 변환) |

## 다른 MCP 도구에서 쓰기 (Claude 외: Gemini CLI·OpenAI Codex·공식 SDK·Inspector)
hwpai 의 MCP 서버(`hwpai.bat mcp`, 도구 8개)는 MCP 표준(JSON-RPC 2.0, 표준입출력, 프로토콜 2025-06-18·2025-03-26·2024-11-05)을 따르므로 이 전송 방식을 지원하는 도구에는 같은 방식으로 등록한다. **전송은 표준입출력(내 PC에서 서버를 띄우는 방식) 하나뿐**이다. 인터넷 주소(HTTP)로 받는 서버는 없다. 아래 `D:\hwpai` 는 휴대용 폴더를 푼 위치의 예이니 본인 경로로 바꾼다. 등록은 **사람이 설정 파일에 직접 적거나 승인한 뒤에만** 한다.

**어느 쪽으로 등록하나** — `hwpai.bat`(권장)은 파이썬·node 위치를 스스로 잡으므로 환경변수를 따로 줄 필요가 없다. 클라이언트가 `.bat` 을 직접 띄우지 못하면 `D:\hwpai\python\python.exe` 에 인자 `-m hwpai mcp` 를 준다(포함된 파이썬이 `..\app` 을 이미 찾는다: `python\python312._pth`). **`PYTHONPATH` 환경변수는 쓰지 않는다** — Gemini CLI 가 막는다(아래).

| 도구 | 등록 위치와 형식 | 확인 |
|---|---|---|
| Claude 데스크톱 | `hwpai.bat mcp-install` 또는 `hwpai.bat mcp-setup install --target claude` (승인 후 설정 파일에 기록, 기존 설정은 `.bak`) | 2026-11-04·11-08 사용자 PC에서 도구 호출 성공(이전 기록) |
| Gemini CLI | `%USERPROFILE%\.gemini\settings.json`(전체) 또는 작업 폴더 `.gemini\settings.json` 의 `mcpServers` | 아래 표 |
| OpenAI Codex(CLI·앱 공용) | `%USERPROFILE%\.codex\config.toml` 의 `[mcp_servers.hwpai]`, 또는 `hwpai.bat mcp-setup install --target chatgpt`(대상 이름은 chatgpt 이지만 쓰는 파일은 Codex 설정) | 아래 표 |
| 공식 MCP SDK·Inspector | 코드에서 `command` = `hwpai.bat`(또는 `python.exe`), `args` = `mcp` 로 표준입출력 연결 | 아래 표 |

**Gemini CLI** (`settings.json`, 공식 문서 docs/tools/mcp-server.md 의 `mcpServers` 형식 — 필드 `command`·`args`·`env`·`cwd`·`timeout`(ms)·`trust`·`includeTools`)
```json
{
  "mcpServers": {
    "hwpai": {
      "command": "D:\\hwpai\\hwpai.bat",
      "args": ["mcp"],
      "timeout": 600000,
      "env": { "HWPAI_MCP_ROOTS": "D:\\업무문서", "HWPAI_GRADE_LOG": "D:\\hwpai_기록" }
    }
  }
}
```
- Gemini CLI 는 **신뢰하지 않은 폴더에서는 표준입출력 서버를 꺼 둔다**(`gemini mcp list` 에 Disabled). 그 폴더를 신뢰한 뒤에야 Connected 가 된다(시험에서 같은 현상을 확인).
- `env` 에 `PYTHONPATH` 를 적으면 「Blocked dangerous environment variable override」로 막혀 Disconnected 가 된다(시험에서 확인). 위 예처럼 `hwpai.bat` 을 쓰거나 `cwd` 를 `D:\hwpai\app` 으로 준다.
- 도구 확인 질문을 줄이려면 `"trust": true` 를 줄 수 있으나, 문서 내용이 모델에 가는 도구이므로 권하지 않는다.

**OpenAI Codex** (`config.toml`, 공식 문서 「MCP」의 `[mcp_servers.<이름>]` — 필드 `command`·`args`·`env`·`cwd`·`startup_timeout_sec`(기본 10)·`tool_timeout_sec`(기본 60)·`enabled_tools`). Windows 경로는 작은따옴표(리터럴 문자열)로 적는다.
```toml
[mcp_servers.hwpai]
command = 'D:\hwpai\hwpai.bat'
args = ['mcp']
startup_timeout_sec = 30
tool_timeout_sec = 600

[mcp_servers.hwpai.env]
HWPAI_MCP_ROOTS = 'D:\업무문서'
HWPAI_GRADE_LOG = 'D:\hwpai_기록'
```
- 변환 도구는 폴더가 크면 60초를 넘길 수 있어 `tool_timeout_sec` 를 늘렸고, 시작 제한은 PC 백신 검사 등을 감안해 30초로 넓혔다(리눅스에서 서버 시작은 0.1초대였고 윈도 시간은 재지 않았다 — 안전 여유값이다).

**공통 환경변수(선택)** — `HWPAI_MCP_ROOTS`: 이 폴더 아래 파일만 다룬다(경로 구분은 윈도 `;`). `HWPAI_GRADE_FILE`: 사람이 만든 등급 파일(CSV). `HWPAI_GRADE_LOG`: 등급 기록(`hwpai_등급기록`)을 둘 폴더 — **정하지 않으면 클라이언트가 서버를 띄운 폴더**에 만들어진다. 이 환경변수들은 위 JSON·TOML 의 `env` 에 넣는다. 등급 인자는 AI 가 도구 인자로 바꿀 수 없다(시험: 거부).

**시험한 것과 못 한 것** (2026-11-21, 리눅스 클라우드 셸·합성 문서·한글 폴더 이름. 결과는 모두 이 작업에서 직접 돌린 값이다)

| 점검 | 결과 |
|---|---|
| 공식 MCP **파이썬 SDK** 2.3.0·1.30.0 — initialize → tools/list → tools/call(read_hwp·get_tables·search_chunks·convert_to_hwpx·audit), ping, 알 수 없는 도구·허용 밖 경로·등급 인자 거부 | 각 15/15 통과 |
| 공식 MCP **Node SDK** 1.29.0 — 같은 흐름 + 입력 스키마 Ajv(JSON Schema 2020-12) 컴파일 + 알 수 없는 메서드 | 10/10 통과 |
| **MCP Inspector** 2.16.0(명령줄 모드) — tools/list, tools/call read_hwp | 통과(도구 8개, 한글 본문) |
| 프로토콜 직접 점검 — protocolVersion 협상(2025-11-25 요청 → 2025-06-18 응답, 2025-03-26·2024-11-05 그대로), capabilities(tools), `notifications/*` 무응답, 초기화 전 ping, id 0·문자열 id, 알 수 없는 메서드 -32601, 파싱 오류 -32700 후 계속, 도구 8개 호출 중 stdout 의 모든 줄이 JSON-RPC(오염 없음) | 통과 |
| 한글 경로·UTF-8 — 한글 폴더·공백 경로 8개 도구 | 통과. **6차 수정**: 파이썬이 UTF-8 모드가 아니면(cp949) 서버가 죽던 오류 고침 |
| 객체가 아닌 JSON(`5`·`"x"`·`null`·`[5]`) 수신 | **6차 수정**: 서버가 죽던 것을 -32600 응답으로 바꿈 |
| **Gemini CLI** 0.70.0 — `gemini mcp list` | 등록 형식 통과·**Connected**(initialize 2025-11-25 협상 후 ping 까지). 신뢰하지 않은 폴더 Disabled·`PYTHONPATH` 차단 확인 |
| **OpenAI Codex** 0.171.0 — `config.toml` 인식(`codex mcp list·get`), 세션 시작 시 서버 기동 | 통과: Codex 가 initialize(2025-06-18)→initialized→tools/list 를 보내고 서버 응답을 받아 `mcp__hwpai` 로 등록, `env` 값 전달 확인. `mcp-setup` 이 쓴 TOML 도 인식 |
| Gemini·Codex 에서 **모델이 도구를 실제로 부르는 시험**(tools/call) | **미실시** — 로그인·API 키 없음. 같은 tools/call 은 위 SDK·Inspector 로만 확인했다 |
| **Windows 에서 `hwpai.bat`·`python.exe` 로 서버를 직접 띄워 initialize → tools/list → tools/call(read_hwp·get_tables·convert_to_hwpx·audit)** | **통과**(2026-11-21, Windows 사무용 PC 실측, 포함 python 3.12.10·합성 문서) — 5경우 모두 통과: ① `hwpai.bat mcp` ② `python.exe -m hwpai mcp`(PYTHONUTF8 미설정, 기본 인코딩 cp949, 한글·공백 경로 문서) ③ `PYTHONUTF8=0 PYTHONIOENCODING=cp949` 명시 ④ `python.exe` 를 `C:\Windows\System32` 에서 띄움(`HWPAI_GRADE_LOG` 없음) ⑤ `hwpai.bat` 을 System32 에서 띄움. 시작~initialize 응답 3회: `hwpai.bat` 0.24·0.23·0.22초, `python.exe` 0.17·0.18·0.17초(처음 한 번은 0.45초). 클라이언트는 포함 python 의 표준 라이브러리 스크립트(Gemini·Codex 가 아님) |
| **Windows 에서 Gemini·Codex 가 서버를 띄우고 모델이 도구를 부르는 시험** | **미실시** — 로컬 설치 단계(npm)가 실패해 중단, 재시도 예정(8차). 구판 휴대용 서버는 System32 에서 띄우면 `hwpai_등급기록` 권한 오류로 도구가 실패하는 것을 윈도에서 확인했다(이 판은 ④·⑤ 에서 통과) |
| Gemini 에 도구 스키마를 넘기는 단계(모델 쪽 검증) | **미실시**(로그인 필요) |

**ChatGPT 웹·온AI** — 이 서버는 내 PC 에서 도는 표준입출력 서버라 웹 서비스에 등록할 수 없다. ChatGPT 웹은 인터넷 주소의 원격 MCP 만 받는 것으로 알려져 있어 등록할 수 없다고 본다(이 작업에서 직접 시험하지 않음). 업무망 온AI(FabriX·CLOVA Studio for GOV 에이전트)는 외부 MCP 등록 기능이 없음을 2026-11-09 사용자가 확인했다. 이 경우에는 **변환 결과(`hwpai.bat convert`·화면의 HWPX·Markdown 내보내기)를 첨부**해 쓴다(행정망 실측 위 표). 인터넷 주소 방식 서버는 결선 규칙상 만들지 않았다.

## 알려진 제약 사항
- **검증 기록**(모두 공개 자료, 측정 코드 판을 함께 적는다)

| 시험 | 결과 |
|---|---|
| 공개 보도자료 1,000건(2017~2021) | 제출 코드 재측정(11-11): PASS 999·FAIL 1(0195), Windows 사무용 PC 245초·리눅스 2코어 102초(동시 2). 「확인 필요」 266건(본문 66·속성만 200) |
| 다른 기관 62건(27개 기관) · 구조 시험 306건 | 62 PASS · PASS 292·WARN 12·FAIL 0 |
| 공개 보도자료 10,501건(2013~2026, 60개 기관) | 처음 측정 PASS 99.91%(95% 신뢰구간 99.84~99.95). 원문을 다시 받아 해시가 같은 10,446건을 C107 코드로 재측정: PASS 10,437·WARN 4·FAIL 4·변환 불가 1, 나빠진 문서 0 |
| 공개 저장소 문서 2,333건(제출 코드 C121) | PASS 2,244·WARN 44·FAIL 1(HWP가 아닌 시험 입력 44건 제외), 이전 판보다 나빠진 문서 0 |
| 한글 13(0,0,3901)과 같은 표본 438건(C93 코드) | 판정 PASS hwpai 437 · 한글 431 · kordoc 436 · hwpConverter 355/405. 한글이 PASS가 아닌 7건은 자동번호 표기·날짜 필드 재계산 같은 표현 차이. 한글 자체 저장이 실패한 8건도 hwpai는 변환 |
| 한글 2024 대량 열기(2,286건) | V8 판 + 스크립트 문서 6건(제출 기본값 재시험) + C120 8건(시험27) + C121 25건(시험29): 모두 열림, 쪽 2,234/2,234, 글 2,224/2,227(남은 3건은 한글이 파일 이름·기호를 새로 쓰는 차이) |
| 독립 채점(hwpai 코드 미사용) · 제3자 스키마 | 글 437/438, 개수 438/438 · python-hwpx 문서 오류 0/446 |

- **한글로 찾아 고친 것**: 숨은 본문(ViewText) 끼어듦, 묶음 안 OLE(엔진 소스 수정. 그림 채운 사각형을 그림으로 바꾸던 수정은 한글 2024 저장본과 달라 결선 보완에서 되돌림), 수식 캡션·표 개체 설명(엔진 소스 수정, 결선 보완), 쪽번호 위치, 각주 번호, 기호 문자, 교정부호 필드, 변경 추적 이력, 필드 속성·커서 위치·하이픈·다단·단 너비·그림자 여백(한글 2,286건 대량 판정으로 찾은 7종), 한컴이 아닌 생성기의 줄 배치 저장값(C120, 8건 — 일괄 제거는 23건이 어긋나 기각), 옛 한글 조판으로 저장된 수식 크기(C121, 25건 — 한컴 저장본 수식 51,745개 대조로 표지 5종을 찾음, 맞던 수식을 바꾼 일 0).
- **남은 것**: 쪽 수 차이 없음(58edc88128ce 22 대 23쪽은 C121로 해결, 시험29). 구버전 한글·온나라 웹기안기 직접 열기는 하지 않았다(구조 검사만 통과).
- **0195**: 변경 추적으로 지운 글(380자)이 남은 문서. 한글 PDF로 화면 글이 hwpai 변환본과 같음을 확인했고, 검증서는 원본 전체 기준 FAIL과 화면 글 기준 PASS를 함께 보여 준다(공식 판정은 보수적으로 FAIL).
- **개인정보 검출**은 형식 기반이다. 「성명:」 표기 없는 본문 속 이름·주소는 잡지 못한다(필요하면 「엄격」).
- **화면 끌어놓기**는 브라우저가 경로를 주지 않아 HWP를 작업 폴더로 복사한다(파일당 200MB). 원본 옆에 결과를 두려면 「경로로 고르기」나 아이콘 끌어놓기. 폴더 이름에 `&`가 있으면 화면을 쓴다.
- **재배포 제한 구성요소: 없음.** rhwp 소스 빌드(MIT, 로컬 수정은 `NOTICE` 1항), Python 3.12 embed(PSF), Node.js 22(MIT), olefile·cryptography·cffi·pycparser. 판·고지는 `NOTICE`·`THIRD_PARTY_LICENSES.md`.

## 개발 경위 요약
기관이 쌓아 온 HWP를 HWPX로 옮기면 글이나 표 칸이 빠지거나 바뀌어도 사람이 한 건씩 맞춰 보기 어렵다. 그래서 변환보다 **증명**을 앞에 두었다: 원본 HWP를 변환 엔진과 다른 판독기로 다시 읽어 변환본과 대조하고, 판정과 근거를 검증서·이관대장으로 남긴다. 공개 보도자료 1,000건으로 반복 측정하며 그림 누락, 화면에 없는 글의 끼어듦, 배포판 엔진의 거짓 PASS를 찾아 고쳤고(엔진은 소스 빌드로 교체), 다음에는 검증기 자체를 의심했다 — hwpai 코드를 쓰지 않는 독립 채점기, 제3자 스키마 검사, 그리고 한글 2024로 2,286건을 원본·변환본 모두 열어 비교해 결함 7종과 저장값 문제 2종(줄 배치·수식 크기)을 더 찾아 고쳐 쪽 수까지 2,234/2,234 원본과 같게 맞췄다. 현장에서는 폴더를 끌어다 놓기만 하면 되고, 행정망에서는 변환 결과를 업무망 온AI 모델 3종에 넣어 실제로 썼다.
