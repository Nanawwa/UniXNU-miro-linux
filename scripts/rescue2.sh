#!/bin/bash
set -u
FB=/usr/bin/fastboot
STOCK=${STOCK_DTBO:-/root/k80pro-port/os4pkg/img/dtbo.img}
LOG=$R/rescue.log
: > "$LOG"
log(){ echo "[$(date -u '+%H:%M:%S')] $*" | tee -a "$LOG"; }
log "rescue2: 0.2s polling for a fastboot device"
for i in $(seq 1 4000); do
  D=$(timeout 2 $FB devices 2>/dev/null)
  if echo "$D" | grep -q fastboot; then
    log "fastboot seen at attempt $i: $D"
    timeout 6 $FB --set-active=a 2>&1 | tail -1 | tee -a "$LOG"
    OUT=$(timeout 20 $FB flash dtbo_b "$STOCK" 2>&1)
    echo "$OUT" | tail -2 | tee -a "$LOG"
    echo "$OUT" | grep -q Finished && log "stock dtbo_b restored" || log "dtbo restore incomplete"
    timeout 8 $FB reboot 2>&1 | tail -1 | tee -a "$LOG"
    log "RESCUE2 DONE"
    exit 0
  fi
  sleep 0.2
done
log "RESCUE2 TIMEOUT"
