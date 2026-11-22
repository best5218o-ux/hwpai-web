#!/bin/bash
# 사용: run_nchunk.sh <i> [chunk크기=175] — 신규표본 i번째 묶음을 14개 도구로 변환 + 독립 채점 후 변환물 삭제
export BCN=/home/claude/bcn; i=$1; K=${2:-175}; N=/dev/shm/new; W=$N/w$i; R=/home/claude/bulk_compare_new/raw
S=/tmp/claude-0/-home-claude/2de2d425-f65d-5b12-93ca-373977a7f91a/scratchpad
rm -rf $W; mkdir -p $W/orig $W/hangul $W/out/hancom
ls $N/orig | sort | sed -n "$((i*K+1)),$(((i+1)*K))p" > $W/list.txt
while read f; do cp $N/orig/$f $W/orig/; b=${f%.hwp}; [ -f $N/hangul/$b.hwpx ] && cp $N/hangul/$b.hwpx $W/hangul/; [ -f $N/hancom/$b.hwpx ] && cp $N/hancom/$b.hwpx $W/out/hancom/; done < $W/list.txt
echo "chunk $i files $(ls $W/orig | wc -l) hangul $(ls $W/hangul | wc -l)"
t0=$(date +%s)
mkdir -p $W/out/hwpai
for k in 0 1; do python3 -I -B $S/conv.py /home/claude/core_c102 $W/orig $W/out/hwpai $k 2 > $W/conv_$k.log 2>&1 & done; wait
t1=$(date +%s)
cd /home/claude/bulk_compare_new/tools && TL=rhwp,hwpforge,hwp-convert,hwpxjs,jhwpx,h2h_yuson,h2h_kossembly,h2h_asi,kordoc,hwp2hwpx,pyhwpxlib,hwpConverter; [ -x $BCN/bin/ahwp ] && TL=$TL,ahwp
python3 run_new.py $W/orig $W/out --tools $TL --jobs 2 --timeout 120 > $W/new.log 2>&1
t2=$(date +%s)
cd /home/claude/scorer
TOOLS=""; for d in $W/out/*/; do t=$(basename $d); [ -d $d ] && TOOLS="$TOOLS --tool $t=$d"; done
python3 -I format_score.py --hangul $W/hangul $TOOLS --out $R/fmt_c$i -j 2 | tail -1
python3 -I run_all_score.py --orig $W/orig --hangul $W/hangul $TOOLS --out $R/ind_c$i --cache $W/cache -j 2 2>&1 | tail -1
t3=$(date +%s)
mkdir -p $R/conv_c$i; cp $W/out/results.csv $R/conv_c$i/new_results.csv 2>/dev/null; cat $W/conv_*.log > $R/conv_c$i/hwpai_conv.log
for d in $W/out/*/; do echo "$(basename $d) $(ls $d | wc -l)"; done > $R/conv_c$i/outcounts.txt
echo "hwpai $((t1-t0))s new $((t2-t1))s score $((t3-t2))s" > $R/conv_c$i/timing.txt
cat $R/conv_c$i/outcounts.txt $R/conv_c$i/timing.txt; rm -rf $W; echo CHUNKDONE
