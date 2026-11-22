#!/bin/bash
cd /home/claude/bulk_compare_5th
for i in 03 04 05 06 07 08 09 10 11 12; do
  while [ ! -f ready_$i ]; do sleep 5; done
  while pgrep -f "run_chunk.sh" >/dev/null; do sleep 5; done
  scripts/go.sh $i
done
