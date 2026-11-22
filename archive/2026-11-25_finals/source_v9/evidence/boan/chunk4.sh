#!/bin/bash
# 사용: chunk.sh <i>  — 올라온 bulk_chunk_<i>_* 조각을 풀어 C101·C102 로 변환하고 층1 채점, 그 뒤 자료를 지운다
i=$1; S=<작업폴더>
U=/mnt/user-data/uploads/Downloads/RESTART/_cloudxfer_20261121; W=/home/claude/bulkwork
mkdir -p $W/c$i && cd $W/c$i || exit 1
cat $U/bulk_chunk_${i}_* > all.zip && rm -f $U/bulk_chunk_${i}_* && unzip -q -o all.zip && rm all.zip
[ -d 원본 ] || mv '#Uc6d0#Ubcf8' 원본
for core in c101:/home/claude/hwpai_v9/app/vendor/rhwp-core c102:/home/claude/core_c102; do
  n=${core%%:*}; p=${core#*:}
  for k in 0 1 2 3; do python3 -I -B $S/conv.py $p $W/c$i/원본 $W/c$i/$n $k 4 > $W/c$i/conv_${n}_$k.log 2>&1 & done; wait
done
cd /home/claude/scorer && python3 -I format_score.py --hangul $W/c$i/hangul --tool c101=$W/c$i/c101 --tool c102=$W/c$i/c102 --out $S/fmt_bulk_$i -j 4 | tail -1
cd /home/claude/scorer && python3 -I run_all_score.py --orig $W/c$i/원본 --hangul $W/c$i/hangul --tool c101=$W/c$i/c101 --tool c102=$W/c$i/c102 --out $S/ind_bulk_$i --cache /dev/shm/sc_cache_$i -j 4 2>&1 | tail -1; rm -rf /dev/shm/sc_cache_$i
grep -h FAIL $W/c$i/conv_*.log | head
ls $W/c$i/원본 | wc -l
rm -rf $W/c$i
