#!/bin/bash
cd /home/claude/bulk_compare_new; N=/dev/shm/new
if [ ! -f $N/.ready ]; then source <(sed -n '/^U=/,/^fi/p' chain_new.sh); fi
for i in 0 1 2 3 4 5; do [ -f raw/conv_a$i/timing.txt ] && continue; ./run_ahwp.sh $i > logs/a$i.log 2>&1; done; echo AHWPDONE
