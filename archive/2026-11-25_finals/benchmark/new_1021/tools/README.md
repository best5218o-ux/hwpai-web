# 신규 HWP→HWPX 변환 도구 실행기 (bulk_compare_new/tools)

채점 없음 · 변환만. 채점기(/home/claude/scorer)는 건드리지 않는다. 2026-11-21 도구 조사·설치·보류표본 20건 시험까지 완료, 신규 1,000건 변환은 아직 안 돌렸다.

## 사용
    # 설치 위치(기본 /dev/shm/bcn)가 없으면 먼저: ./install.sh   (npm·PyPI·GitHub 소스, ahwp 는 cargo 빌드 약 7분)
    python3 run_new.py <입력폴더(.hwp)> <출력폴더> [--tools a,b,...] [--jobs 2] [--timeout 120] [--limit N] [--resume]
- 출력: `<출력폴더>/<도구>/<원본SHA256앞12>.hwpx` + `results.csv`(도구, 파일, 상태, 초, 출력크기, 원본SHA12, 메시지). 기존 5차 비교와 같은 이름 규칙.
- 상태: ok / fail / timeout(120초 초과, 프로세스 그룹 강제 종료) / empty(0바이트) / diskfull(출력 폴더 여유 3MB 미만이면 실행 안 함, 도구 실패와 구분). `--resume` 은 diskfull 외 완료 건을 건너뛴다.
- 도구 이름: `rhwp, hwpforge, ahwp, hwp-convert, hwpxjs, jhwpx, h2h_yuson, h2h_kossembly, h2h_asi, ohah_textonly, hwpx-js` (기본 전부).
  기존 도구 `kordoc, hwp2hwpx, pyhwpxlib, hwpConverter` 는 /home/claude/opentools/run_all.py 의 명령을 그대로 재사용하므로 `--tools` 에 이름을 주면 같은 방식으로 돈다. (기존 4종 대량 실행기 /home/claude/bulk_compare_5th/scripts 는 5차 전용 흐름이라 읽기만 했다. hwpai 변환은 거기 conv.py 방식을 따로 쓴다.)
- 출력 폴더는 /dev/shm 처럼 여유 있는 곳을 쓸 것(루트 디스크 여유 약 0.9GB). 1,000건 × 12도구 출력은 약 6~7GB 예상이라 도구별로 나눠 채점 후 삭제 권장.
- 병렬 2(`--jobs 2`)가 기본. 시험 중 cargo 빌드와 CPU를 나눠 쓴 탓에 속도는 보수적이다(재측정 필요).

## 파일
- `run_new.py` 실행기, `install.sh` 설치 재현, `tools_table.csv` 도구표, `test20_results.csv` 보류 20건 시험 원자료(260행)
- `wrappers/` : rhwp_wasm_hwpx.mjs(@rhwp/core exportHwpx), npm_hwptohwpx.mjs(hwpToHwpx 호출), hwpxjs_rw.cjs(hwpx-js read→write), hwpforge_conv.py, java/Hwp2HwpxCli.java(neolord0 README 사용법 그대로)

## 설치 위치와 용량 (모두 /dev/shm/bcn, 루트 디스크 사용 없음)
npm 61MB · venv(hwpforge+hwp2hwpx) 79MB · venv_yuson 15MB · ahwp 바이너리 33MB · jhwpx 소스+빌드 약 65MB · asi jar 2.5MB · 시험 입력 20건 12MB → 합계 약 270MB. (설치 중 최대 약 1.3GB: npm 캐시, cargo target 480MB·registry 143MB, mvn 저장소는 시험 후 삭제.) /dev/shm 은 재부팅하면 사라지므로 install.sh 로 복구.

## 알아둘 것
- 「ok」는 파일이 생기고 zip·section XML·header.xml 이 파싱된다는 뜻이다. 서식·내용 품질은 채점기로 봐야 한다(간이 점검: 모든 도구의 글자 수 중앙값이 yuson 포크 대비 1.00, 글이 0자인 출력 없음).
- 도구 계보가 겹친다: neolord0(hwplib·hwpxlib·hwp2hwpx) 계열은 hwp2hwpx·pyhwpxlib·hwpConverter·h2h_* 4~6종, hwpxjs→hwp-convert(rhwp 파서 포팅), rhwp 자체. 결과가 비슷하면 같은 엔진이라 독립 표본이 아니다.
- 한컴 변환기·hwpai 는 이 폴더 범위 밖(PC 쪽 다른 에이전트가 처리).
