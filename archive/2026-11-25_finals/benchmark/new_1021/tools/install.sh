#!/bin/bash
# 신규 HWP→HWPX 도구 설치 (재현용). 설치 위치 BCN(기본 /dev/shm/bcn). 필요: node 22, python3, JDK 21, maven, cargo(ahwp 빌드 7분), git, 외부망(npm·PyPI·GitHub 소스)
set -e
export BCN=${BCN:-/dev/shm/bcn}; mkdir -p $BCN/src $BCN/bin $BCN/asi; cd $BCN
export npm_config_cache=$BCN/.npmcache
# 1) npm: rhwp(@rhwp/core 0.9.1 WASM), hwp-convert 1.13.0, @ssabrojs/hwpxjs 0.4.0, @ohah/hwpjs 0.1.1, hwpx-js 0.1.2
mkdir -p npm && (cd npm && npm init -y >/dev/null && npm i hwp-convert@1.13.0 @ssabrojs/hwpxjs@0.4.0 @ohah/hwpjs@0.1.1 @rhwp/core@0.9.1 hwpx-js@0.1.2 --omit=optional)
# 2) PyPI: hwpforge 0.20.1, hwp2hwpx 1.0.1(kossembly)  (rhwp-python·unhwp 은 쓰지 않음)
python3 -m venv venv && ./venv/bin/pip install -q hwpforge==0.20.1 hwp2hwpx==1.0.1
# 3) GitHub 소스: jhwpx-converter(199f098), hwp2hwpx yuson0701 포크(deaea5f), asi0818 포크(edc0527), agent-hwp(785f7ae)
cd src
git clone -q https://github.com/damulhan/jhwpx-converter jhwpx-converter-damulhan && (cd jhwpx-converter-damulhan && git checkout -q 199f098 && npm i >/dev/null && npx tsc)
git clone -q https://github.com/yuson0701/hwp2hwpx hwp2hwpx-yuson0701 && (cd hwp2hwpx-yuson0701 && git checkout -q deaea5f) && python3 -m venv ../venv_yuson && ../venv_yuson/bin/pip install -q ./hwp2hwpx-yuson0701
git clone -q https://github.com/asi0818/hwp2hwpx hwp2hwpx-asi0818 && (cd hwp2hwpx-asi0818 && git checkout -q edc0527 && sed -i 's#compiler.source>7#compiler.source>8#; s#compiler.target>7#compiler.target>8#' pom.xml && mvn -q -Dmaven.repo.local=$BCN/m2 -Dmaven.test.skip=true package)
cp hwp2hwpx-asi0818/target/hwp2hwpx-1.0.0.jar ../asi/; cp /home/claude/opentools/java/lib/hwplib-1.1.10.jar /home/claude/opentools/java/lib/hwpxlib-1.0.9.jar ../asi/
mkdir -p ../asi/out && javac -nowarn -cp "../asi/*" -d ../asi/out /home/claude/bulk_compare_new/tools/wrappers/java/Hwp2HwpxCli.java
git clone -q https://github.com/STAIxBWLB/agent-hwp agent-hwp && (cd agent-hwp && git checkout -q 785f7ae && CARGO_HOME=/dev/shm/cg/cargo CARGO_TARGET_DIR=/dev/shm/cg/target cargo build --release -p agent-hwp) && cp /dev/shm/cg/target/release/ahwp $BCN/bin/ahwp && rm -rf /dev/shm/cg
echo done
