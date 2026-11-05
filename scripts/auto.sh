#!/bin/bash
# Fully unattended reader: boot slots are kept invalid so ABL always lands in
# fastboot by itself. No key presses, no BCB.
set -u
R=${READER_BASE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
FB=/usr/bin/fastboot
KEY=$R/out/reader-ssh-ed25519
LOG=$R/auto.log
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=6 root@10.42.0.2"
log(){ echo "[$(date -u '+%H:%M:%S')] $*" | tee -a "$LOG"; }
: > "$LOG"
ROUNDS=${1:-3}
IMG=${IMG:-$R/out/boot-miro-v32/boot.img}
DTBO=${DTBO:-$R/out/boot-miro-v33/dtbo.img}
for round in $(seq 1 "$ROUNDS"); do
  log "===== round $round/$ROUNDS ====="
  GOT=0
  for i in $(seq 1 60); do
    timeout 2 $FB devices 2>/dev/null | grep -q fastboot && { GOT=1; log "fastboot after ${i}s"; break; }
    sleep 1
  done
  [ $GOT = 1 ] || { log "device not in fastboot"; exit 2; }
  timeout 8 $FB --set-active=b >/dev/null 2>&1
  OUT=$(timeout 30 $FB flash dtbo_b "$DTBO" 2>&1)
  echo "$OUT" | grep -q Finished || { log "dtbo flash failed"; exit 3; }
  timeout 25 $FB boot "$IMG" 2>&1 | tail -1 | tee -a "$LOG"
  I=""
  for i in $(seq 1 400); do for n in $(ls /sys/class/net 2>/dev/null); do case "$n" in enx*) I=$n;; esac; done; [ -n "$I" ] && break; sleep 0.1; done
  [ -z "$I" ] && { log "no NCM"; exit 5; }
  ip link set $I up; ip addr replace 10.42.0.1/24 dev $I >/dev/null 2>&1
  OOPS=""
  for i in $(seq 1 40); do
    OOPS=$(timeout 6 $SSH 'for b in /sys/class/block/*; do grep -qx "PARTNAME=oops" $b/uevent 2>/dev/null && basename $b; done' 2>/dev/null | head -1)
    [ -n "$OOPS" ] && break
    sleep 2
  done
  [ -z "$OOPS" ] && { log "no UFS"; exit 6; }
  DEST=$R/out/oops-auto-r$round.bin
  timeout 60 $SSH "dd if=/dev/$OOPS of=/run/oops.bin bs=1M count=16 status=none" 2>&1 | tee -a "$LOG"
  timeout 120 ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o BatchMode=yes -o LogLevel=ERROR root@10.42.0.2 'cat /run/oops.bin' > "$DEST" 2>/dev/null
  SZ=$(stat -c%s "$DEST" 2>/dev/null || echo 0)
  log "pulled $SZ bytes"
  if [ "$SZ" = 16777216 ]; then
    python3 $R/scripts/parse-oops.py "$DEST" --log-out "${DEST%.bin}.txt" 2>&1 | head -6 | tee -a "$LOG"
  fi
  log "reboot (ABL returns to fastboot on its own)"
  timeout 8 $SSH 'sync; busybox reboot -f' >/dev/null 2>&1 || true
  sleep 12
done
log "all rounds done"
