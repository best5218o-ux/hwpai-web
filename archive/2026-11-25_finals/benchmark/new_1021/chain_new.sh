#!/bin/bash
# 재시작에 안전한 연쇄 실행: 데이터가 /dev/shm 에 없으면 uploads 의 zip 에서 풀고, 끝난 묶음은 건너뛴다. 사용: chain_new.sh [시작 묶음=0] [끝=5]
U=/mnt/user-data/uploads/Downloads/RESTART/hwpai_신규표본_20261121/_stage; N=/dev/shm/new
if [ ! -f $N/.ready ]; then
  rm -rf $N; mkdir -p $N/orig $N/hangul $N/hancom
  (cd $N/orig && for z in $U/o*.zip; do unzip -qo $z; done); (cd $N/hangul && for z in $U/h*.zip; do unzip -qo $z; done); (cd $N/hancom && for z in $U/c*.zip; do unzip -qo $z; done)
  touch $N/.ready
fi
cd /home/claude/bulk_compare_new
for i in $(seq ${1:-0} ${2:-5}); do
  [ -f raw/conv_c$i/timing.txt ] && continue
  ./run_nchunk.sh $i > logs/c$i.log 2>&1
done
echo CHAINDONE >> logs/chain.log
