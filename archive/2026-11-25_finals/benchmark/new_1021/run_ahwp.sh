#!/bin/bash
# 사용: run_nchunk.sh <i> [chunk크기=175] — 신규표본 i번째 묶음을 14개 도구로 변환 + 독립 채점 후 변환물 삭제
export BCN=/home/claude/bcn; i=$1; K=${2:-175}; N=/dev/shm/new; W=$N/a$i; R=/home/claude/bulk_compare_new/raw
S=/tmp/claude-0/-home-claude/2de2d425-f65d-5b12-93ca-373977a7f91a/scratchpad
rm -rf $W; mkdir -p $W/orig $W/hangul $W/out
ls $N/orig | sort | sed -n "$((i*K+1)),$(((i+1)*K))p" > $W/list.txt
while read f; do cp $N/orig/$f $W/orig/; b=${f%.hwp}; [ -f $N/hangul/$b.hwpx ] && cp $N/hangul/$b.hwpx $W/hangul/; done < $W/list.txt
echo "chunk $i files $(ls $W/orig | wc -l) hangul $(ls $W/hangul | wc -l)"
t0=$(date +%s)
t1=$(date +%s)
cd /home/claude/bulk_compare_new/tools && TL=ahwp
python3 run_new.py $W/orig $W/out --tools $TL --jobs 2 --timeout 120 > $W/new.log 2>&1
t2=$(date +%s)
cd /home/claude/scorer
TOOLS=""; for d in $W/out/*/; do t=$(basename $d); [ -d $d ] && TOOLS="$TOOLS --tool $t=$d"; done
python3 -I format_score.py --hangul $W/hangul $TOOLS --out $R/fmt_a$i -j 2 | tail -1
python3 -I run_all_score.py --orig $W/orig --hangul $W/hangul $TOOLS --out $R/ind_a$i --cache $W/cache -j 2 2>&1 | tail -1
t3=$(date +%s)
mkdir -p $R/conv_a$i; cp $W/out/results.csv $R/conv_a$i/new_results.csv 2>/dev/null; 
for d in $W/out/*/; do echo "$(basename $d) $(ls $d | wc -l)"; done > $R/conv_a$i/outcounts.txt
echo "hwpai $((t1-t0))s new $((t2-t1))s score $((t3-t2))s" > $R/conv_a$i/timing.txt
cat $R/conv_a$i/outcounts.txt $R/conv_a$i/timing.txt; rm -rf $W; echo CHUNKDONE
