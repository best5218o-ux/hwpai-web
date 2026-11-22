#!/bin/bash
# 사용: run_chunk.sh <NN> — /dev/shm/bw/cNN 에 풀린 원본·hangul 로 4개 도구 변환 + 독립 채점(층1 서식·독립 글/개수) 후 변환물 삭제
i=$1; W=/dev/shm/bw/c$i; R=/home/claude/bulk_compare_5th/raw
S=/tmp/claude-0/-home-claude/2de2d425-f65d-5b12-93ca-373977a7f91a/scratchpad
cd $W || exit 1
[ -d 원본 ] || mv '#Uc6d0#Ubcf8' 원본
mkdir -p hwpai
t0=$(date +%s)
# hwpai v9 + C102 (5차) — 코어 2개라 프로세스 2
for k in 0 1; do python3 -I -B $S/conv.py /home/claude/core_c102 $W/원본 $W/hwpai $k 2 > $W/conv_$k.log 2>&1 & done; wait
t1=$(date +%s)
# 공개 도구 3종 (보류 532건과 같은 run_all.py, 기본 옵션: timeout 120s, jobs 2)
(cd /home/claude/opentools && python3 run_all.py $W/원본 $W/ot --tools kordoc,hwp2hwpx,pyhwpxlib --jobs 2 > $W/ot.log 2>&1)
t2=$(date +%s)
cd /home/claude/scorer
TOOLS="--tool hwpai=$W/hwpai --tool kordoc=$W/ot/kordoc --tool hwp2hwpx=$W/ot/hwp2hwpx --tool pyhwpxlib=$W/ot/pyhwpxlib"
python3 -I format_score.py --hangul $W/hangul $TOOLS --out $R/fmt_c$i -j 2 | tail -1
python3 -I run_all_score.py --orig $W/원본 --hangul $W/hangul $TOOLS --out $R/ind_c$i --cache $W/cache -j 2 2>&1 | tail -1
t3=$(date +%s)
mkdir -p $R/conv_c$i; cp $W/ot/results.csv $R/conv_c$i/opentools_results.csv; cat $W/conv_*.log > $R/conv_c$i/hwpai_conv.log
echo "conv_hwpai $((t1-t0))s opentools $((t2-t1))s score $((t3-t2))s" > $R/conv_c$i/timing.txt
for t in hwpai kordoc hwp2hwpx pyhwpxlib; do d=$W/$t; [ $t = hwpai ] || d=$W/ot/$t; echo "$t $(ls $d 2>/dev/null | wc -l)"; done > $R/conv_c$i/outcounts.txt
cat $R/conv_c$i/outcounts.txt; cat $R/conv_c$i/timing.txt
rm -rf $W
