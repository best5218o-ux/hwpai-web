# 제3자 구성요소와 라이선스

휴대용 폴더(hwpai-portable-win64)에 실제로 들어 있는 것만 적는다. 고지 원문 위치를 함께 적었다.

## 1. 동봉 구성요소

| 구성요소 | 판 | 위치 | 라이선스 | 고지 원문 | 바꿨나 |
|---|---|---|---|---|---|
| rhwp 변환 엔진(WASM) | 소스 빌드 0.9.0-local (커밋 c9095c5f, Cargo 0.9.0) | app/vendor/rhwp-core | MIT (Edward Kim) | app/vendor/rhwp-core/LICENSE, licenses/rhwp-MIT-LICENSE.txt | 4개 파일 96줄 추가·1줄 삭제(아래 1-1) |
| Python embeddable | 3.12.10 (win amd64) | python/ | PSF License | python/LICENSE.txt | 아니오 |
| ├ OpenSSL (libcrypto-3·libssl-3) | Python 배포본 포함 | python/ | Apache-2.0 | python/LICENSE.txt | 아니오 |
| ├ libffi | Python 배포본 포함 | python/ | MIT | python/LICENSE.txt | 아니오 |
| ├ SQLite | Python 배포본 포함 | python/ | 공개 도메인 | python/LICENSE.txt | 아니오 |
| └ vcruntime140·vcruntime140_1 | Python 배포본 포함 | python/ | Microsoft Visual C++ 재배포 조건(Python 공식 embed 배포본에 들어 있는 재배포 허용 파일) | python/LICENSE.txt | 아니오 |
| Node.js | 22.23.4 (win x64) | node/node.exe | MIT 등 | node/LICENSE | 아니오 |
| olefile | 0.47 | python/Lib/site-packages | BSD 계열 | olefile-0.47.dist-info/LICENSE.txt | 아니오 |
| cryptography | 50.0.2 | python/Lib/site-packages | Apache-2.0 OR BSD-3-Clause | cryptography-50.0.2.dist-info/licenses | 아니오 |
| cffi | 2.1.1 | python/Lib/site-packages | MIT-0 | cffi-2.1.1.dist-info/licenses | 아니오 |
| pycparser | 3.12 | python/Lib/site-packages | BSD-3-Clause | pycparser-3.12.dist-info/licenses | 아니오 |

내려받은 원본 파일의 출처와 SHA256은 `licenses/portable-provenance.txt`에 있다.

### 1-1. rhwp 소스 빌드에서 바꾼 것

| 파일 | 내용 |
|---|---|
| src/serializer/hwpx/context.rs | 그림 원래 픽셀 크기를 한 번 읽어 두는 표(이미지 사각형 → 그림 변환용) |
| src/serializer/hwpx/section.rs | 이미지로 채운 단순 사각형을 그림 개체(hp:pic)로 저장 |
| src/serializer/hwpx/shape.rs | 위 변환 함수 + 글상자·캡션이 있는 사각형은 그대로 두는 가드 |
| src/parser/control/shape.rs | 묶음(그룹) 개체 안의 OLE 를 OLE 개체로 읽음(이전에는 사각형으로 떨어짐, C100) |

변경 추적으로 지운 글을 HWPX에 넣지 않는 동작은 빌드에 쓴 rhwp 소스(커밋 c9095c5f)의 동작이다. hwpai 뒤처리(tracked.py, C95)가 원본의 이력을 한컴 표기로 다시 싣는다.
npm 배포본 0.8.7은 이 글을 넣었고, hwpai 검증서가 이를 찾아내(1,000건 중 0195) 엔진을 이 소스 빌드로 바꿨다.

### 1-2. rhwp_bg.wasm 에 정적으로 들어갈 수 있는 Rust 크레이트

`Cargo.lock` 기준 상한 목록 375개(`licenses/rhwp-rust-deps.csv`, crates.io API로 한 건씩 조회). 네이티브 전용·개발 도구까지 포함한 상위집합이다.

| 판별 라이선스 | 개수 |
|---|---|
| MIT OR Apache-2.0 (표기 변형 포함) | 261 |
| MIT | 43 |
| Zlib·Apache-2.0·MIT 중 택일 | 16 |
| BSD-3-Clause | 8 |
| Unlicense OR MIT | 8 |
| Apache-2.0 | 7 |
| 그 밖의 허용형 조합(ISC·CC0·0BSD·BSL-1.0·Unicode-3.0 등) | 나머지 |
| MIT OR Apache-2.0 OR LGPL-2.1-or-later (r-efi 2개) | 2 — MIT/Apache-2.0을 택하며, UEFI 전용이라 WASM에 들어가지 않는다 |

## 2. 재배포 제한 점검

| 구분 | 결과 |
|---|---|
| GPL·AGPL 단독 | 없음 |
| MPL·EPL·CDDL·SSPL·BUSL | 없음 |
| 고지 의무(BSD·Apache·PSF 등) | 위 표의 고지 원문을 휴대용 폴더에 함께 넣어 충족 |
| 글꼴 | 동봉하지 않음(rhwp_bg.wasm 안에는 글꼴 이름 문자열만 있다) |

## 3. 포함하지 않음

| 구성요소 | 라이선스 | 처리 |
|---|---|---|
| pyhwp(hwp5proc) | GNU AGPL v3 | 비교 평가에서 외부 명령으로만 실행. 배포물에 없음, import 하지 않음 |
| 시험 문서(보도자료·rhwp 시험 문서) | 각 원 저작자 | 실측에만 사용, 배포물에 넣지 않음 |
