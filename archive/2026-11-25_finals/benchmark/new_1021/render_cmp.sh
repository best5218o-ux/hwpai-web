#!/bin/bash
# 532건 렌더 대조: uploads 의 PDF zip 을 /dev/shm/rd 에 풀고 compare_render.py 실행(재시작에 안전: 이미 푼 폴더는 재사용)
U=/mnt/user-data/uploads/Downloads/RESTART/hwpai_보류표본_20261120/render/_stage; D=/dev/shm/rd/pdf
mkdir -p $D; cd $D
for t in 원본 hangul hwpai kordoc hancomconv hwp2hwpx hwpConverter pyhwpxlib; do
  mkdir -p $t; for z in $U/${t}_*.zip; do unzip -qo $z -d $t; done
done
ls | while read t; do echo $t $(ls $t | wc -l); done
cd /home/claude/scorer/render && python3 -I compare_render.py --ref $D/원본 --tool hwpai=$D/hwpai --tool hancom=$D/hancomconv --tool kordoc=$D/kordoc --tool hwp2hwpx=$D/hwp2hwpx --tool hwpConverter=$D/hwpConverter --tool pyhwpxlib=$D/pyhwpxlib --tool hangul_control=$D/hangul --out /home/claude/bulk_compare_new/raw/render532 -j 2
echo RENDERDONE
