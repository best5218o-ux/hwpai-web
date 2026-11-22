#!/bin/bash
# 사용: chunk5.sh <i> — 올라온 bulk_chunk_<i>_* 조각을 풀어 5차(C102 엔진 + 5차 뒤처리)로 변환하고 층1·독립 채점, 그 뒤 자료를 지운다
i=$1; S=<작업폴더>
U=/mnt/user-data/uploads/Downloads/RESTART/_cloudxfer5; W=/home/claude/bulkwork
mkdir -p $W/c$i && cd $W/c$i || exit 1
cat $U/bulk_chunk_${i}_* > all.zip && rm -f $U/bulk_chunk_${i}_* && unzip -q -o all.zip && rm all.zip
[ -d 원본 ] || mv '#Uc6d0#Ubcf8' 원본
for k in 0 1 2 3; do python3 -I -B $S/conv.py /home/claude/core_c102 $W/c$i/원본 $W/c$i/r5 $k 4 > $W/c$i/conv_$k.log 2>&1 & done; wait
cd /home/claude/scorer && python3 -I format_score.py --hangul $W/c$i/hangul --tool r5=$W/c$i/r5 --out $S/fmt5_bulk_$i -j 4 | tail -1
python3 -I run_all_score.py --orig $W/c$i/원본 --hangul $W/c$i/hangul --tool r5=$W/c$i/r5 --out $S/ind5_bulk_$i --cache /dev/shm/sc_cache_$i -j 4 2>&1 | tail -1; rm -rf /dev/shm/sc_cache_$i
grep -h FAIL $W/c$i/conv_*.log | head
ls $W/c$i/원본 | wc -l
rm -rf $W/c$i
