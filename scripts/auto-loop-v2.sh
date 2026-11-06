#!/bin/bash
# Fully unattended debug loop for the miro port. Verified 2026-11-07.
#
# One round:
#   boot XNU image (RAM) -> miro_record_crash() writes the panic record and
#   PSCI-resets the phone after miro-autoreset seconds -> ABL lands in fastboot
#   on its own -> boot reader with its DTBO -> pull oops over ssh -> parse ->
#   reboot reader -> next round.
#
# Measured on 2026-11-07 with the user NOT touching the phone:
#   crash-reset-verify.log: device left fastboot, RETURNED after 200 s.
#   The oops dump from that round contained "miro crash: launchd pid 1" with
#   namespace 6, written before the reset.
set -u
ROUNDS=${1:-3}
IMG=${2:-/root/k80pro-port/boot-crash-reset.img}
FB=/usr/bin/fastboot
R=/root/k80pro-port/linux-reader
OUT=/root/k80pro-port/auto-rounds
KEY=$R/out/reader-ssh-ed25519
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=10 root@10.42.0.2"
mkdir -p "$OUT"
LOG=$OUT/loop.log
: > "$LOG"
log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$LOG"; }

wait_fastboot() {
  local limit=$1 i
  for i in $(seq 1 "$limit"); do
    timeout 3 $FB devices 2>/dev/null | grep -q fastboot && return 0
    sleep 8
  done
  return 1
}

wait_no_fastboot() {
  local i
  for i in $(seq 1 15); do
    timeout 2 $FB devices 2>/dev/null | grep -q fastboot || return 0
    sleep 1
  done
  return 1
}

reader_up() {
  local iface=""
  for i in $(seq 1 70); do
    iface=$(ip -o link 2>/dev/null | grep "02:66:77:88:99:aa" | grep -o "^[0-9]*: [^:@]*" | cut -d' ' -f2)
    [ -n "$iface" ] && break
    sleep 1
  done
  [ -z "$iface" ] && return 1
  ip addr add 10.42.0.1/24 dev "$iface" 2>/dev/null
  ip link set "$iface" up
  for i in $(seq 1 30); do $SSH true 2>/dev/null && return 0; sleep 2; done
  return 1
}

for round in $(seq 1 "$ROUNDS"); do
  log "===== round $round/$ROUNDS ====="
  wait_fastboot 20 || { log "no fastboot at round start"; break; }

  log "booting XNU image"
  timeout 25 $FB boot "$IMG" 2>&1 | tail -1 | tee -a "$LOG"
  # critical: the device must actually leave fastboot before we start timing,
  # otherwise the first poll hits a stale state and reports a false return.
  if ! wait_no_fastboot; then
    log "device never left fastboot; skipping"
    continue
  fi
  log "device left fastboot; waiting for the PSCI reset (up to 320 s)"
  if wait_fastboot 40; then
    log "phone returned to fastboot on its own"
  else
    log "no auto-return within 320 s; skipping reader this round"
    continue
  fi

  log "flashing reader DTBO and booting reader"
  timeout 20 $FB --set-active=b >/dev/null 2>&1
  timeout 30 $FB flash dtbo_b "$R/out/boot-miro-v33/dtbo.img" >/dev/null 2>&1
  timeout 60 $FB boot "$R/out/boot-miro-v32/boot.img" >/dev/null 2>&1
  if ! reader_up; then
    log "reader never came up"
    continue
  fi
  log "reader ssh up"
  sleep 8   # UFS partitions enumerate a few seconds after ssh comes up
  dev=$($SSH 'for b in /sys/class/block/*; do grep -qx PARTNAME=oops $b/uevent 2>/dev/null && basename $b; done' 2>/dev/null | head -1)
  if [ -z "${dev:-}" ]; then
    sleep 8
    dev=$($SSH 'for b in /sys/class/block/*; do grep -qx PARTNAME=oops $b/uevent 2>/dev/null && basename $b; done' 2>/dev/null | head -1)
  fi
  if [ -n "${dev:-}" ]; then
    dest="$OUT/r$round-oops.bin"
    $SSH "dd if=/dev/$dev of=/run/o.bin bs=1M count=16 status=none" 2>/dev/null
    $SSH "cat /run/o.bin" > "$dest" 2>/dev/null
    log "oops dump: $(wc -c < "$dest") bytes"
    python3 /root/k80pro-port/UniXNU-miro-linux/scripts/parse-mirolog.py "$dest" \
        > "$OUT/r$round-report.txt" 2>&1
    sed -n '/panic text/,$p' "$OUT/r$round-report.txt" | head -6 | tee -a "$LOG"
  else
    log "oops partition not found (reader UFS did not enumerate)"
  fi
  # reboot -f drops the device instantly; ssh would otherwise hang forever.
  timeout 6 $SSH -o ServerAliveInterval=1 -o ServerAliveCountMax=2 "reboot -f" 2>/dev/null || true
  sleep 8
done
log "===== loop complete ($ROUNDS rounds) ====="
