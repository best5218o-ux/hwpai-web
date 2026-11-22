#!/bin/bash
# 사용: go.sh <NN> — 올라온 조각 p<NN>_* 를 합쳐 풀고 run_chunk 실행(백그라운드용)
i=$1; U=/mnt/user-data/uploads/Downloads/RESTART/_cloudxfer_bulk6; W=/dev/shm/bw/c$i
mkdir -p $W && cd $W && cat $U/p${i}_?? > /dev/shm/z$i.zip && rm -f $U/p${i}_?? && unzip -q /dev/shm/z$i.zip && rm /dev/shm/z$i.zip
cd /home/claude/bulk_compare_5th && (time scripts/run_chunk.sh $i) > logs/c$i.log 2>&1
