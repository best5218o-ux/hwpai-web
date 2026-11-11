# 제3자 구성요소 고지 (hwpai 웹)

| 구성요소 | 용도 | 라이선스 | 파일 |
|---|---|---|---|
| **rhwp** 0.9.0-local (WebAssembly) — Copyright (c) 2025-2026 Edward Kim, https://github.com/edwardkim/rhwp | HWP→HWPX 변환 엔진 | **MIT** | `vendor/rhwp-core/` · `licenses/rhwp-MIT-LICENSE.txt` · 의존 크레이트 `licenses/rhwp-THIRD_PARTY_LICENSES.md`, `rhwp-rust-deps.csv` |
| hwpai 본체 (Python, 변경 없이 복사) — Copyright (c) 2026 김영민 | 판독·검증서·민감정보·내보내기 | MIT | `py/hwpai/` · `licenses/hwpai-LICENSE.txt` |
| Pyodide 0.27.7 (CPython 3.12 의 WebAssembly 판) | 브라우저에서 hwpai 실행 | MPL-2.0 (Python 은 PSF) | `vendor/pyodide/` · `licenses/pyodide-MPL-2.0.txt` — 소스: https://github.com/pyodide/pyodide |
| olefile 0.47 | HWP(OLE) 읽기 | BSD 계열 | `py/olefile/` · `licenses/olefile-LICENSE.txt` |

rhwp 에 hwpai 가 더한 변경(그림 사각형 가드 등, 소스 3개 파일)은 데스크톱판 NOTICE 에 적힌 대로이며 wasm 은 데스크톱판과 같은 파일이다(SHA-256 은 검증결과.md).
`py/cryptography/` 는 진짜 cryptography 패키지가 아니라, 배포용 HWP 의 AES-128 ECB 복호화만 브라우저(JS)로 넘기는 hwpai 웹 전용 대체 모듈이다.
