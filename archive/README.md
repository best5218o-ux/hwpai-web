# HWP AI 어댑터 — 기록 보관함

2026 공공 AI 대전환 챌린지 세션1 출품작 「HWP AI 어댑터 - HWP를 AI가 바로 읽고 HWPX로 바꾸는 어댑터」(대전서부소방서 문화119안전센터 김영민)의 기록입니다.

공공 GitLab(gitlab.aigov.go.kr/best5218/hwpai)이 2026-11-12부터 점검으로 접속되지 않아, GitLab에 올린 제출본과 그 뒤 결선 보완 작업을 이 저장소에 함께 보관합니다.

| 폴더 | 내용 |
|---|---|
| [`2026-11-11_gitlab_submission/`](2026-11-11_gitlab_submission/) | **11/11 제출본 — 수정하지 않은 원본** |
| ├ `source/` | GitLab 저장소에 올린 소스(소스_hwpai.zip을 푼 것, 해시 대조 완료) |
| ├ `release_v1.0/` | GitLab 릴리스 v1.0 첨부 3종: 휴대용 프로그램(Windows), 웹판, SHA256SUMS |
| └ `submitted_docs/` | 메일로 낸 구동안내서·시연영상, 참고 성능비교평가서, 작동 확인 기록, GitLab 등록 정보 |
| [`2026-11-25_finals/`](2026-11-25_finals/) | **결선(11/25) 준비 — 기존 기능의 개선·보완** |
| ├ `source_v9/` | 결선 보완판 소스 v9(Python·Node 실행기 제외). 보완 내용은 `결선보완_오류수정_기록.md` |
| ├ `engine_patch/` | 변환 엔진(rhwp) C102 보완 패치 — 표·칸 크기 원본값 보존 등 |
| ├ `presentation/` | 시연 해설 영상 2개 |
| └ `benchmark/` | 한글 2024 저장본 기준 비교 검증 요약(신규 1,021건·대량 2,538건)과 채점 스크립트 |

- 웹판(현장 시연용): https://best5218o-ux.github.io/hwpai-web/?demo
- 제출본 해시: `2026-11-11_gitlab_submission/submitted_docs/SHA256SUMS_제출묶음.txt`, `release_v1.0/SHA256SUMS.txt`
- 개인 연락처가 들어 있는 참가신청서는 올리지 않았습니다.
- 비교 검증에 쓴 문서 원본·변환본(공개 보도자료 등)은 용량과 출처 문제로 올리지 않고 요약·채점 결과만 둡니다.
