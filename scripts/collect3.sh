#!/bin/bash
# Collect every channel the board writes, from the place each one actually lives.
#
# The previous collector read only the oops partition, where MIROLOG2 is not
# written: BootLog.c puts the console ring in the last 32 MiB of the root
# partition (userdata), and only the probe and the panic record live in oops.
# That is why every round reported the same 32 stale OOPSLOG1 rounds.
#
# Layout (verified against drivers/MiroUfs/MiroUfs.cpp and package/BootLog.c):
#   userdata LBA 128611072 .. 128619263   8192 blocks   MIROLOG2 console ring
#   oops, last 9 blocks                   36 KiB        probe + panic record
#
# Usage: collect.sh TAG
#   writes /root/k80pro-port/collect3/<TAG>-{log,oops}.bin and prints a summary
set -u
TAG=${1:-run}
FB=/usr/bin/fastboot
R=/root/k80pro-port/linux-reader
OUT=/root/k80pro-port/collect3
KEY=$R/out/reader-ssh-ed25519
D="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=6 root@10.42.0.2"
mkdir -p "$OUT"

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

log "waiting for fastboot"
for i in $(seq 1 120); do
  timeout 3 $FB devices 2>/dev/null | grep -q fastboot && break
  sleep 8
done
timeout 3 $FB devices 2>/dev/null | grep -q fastboot || { log "no fastboot"; exit 1; }

# the reader needs its overlay in the active slot or UFS never comes up
timeout 20 $FB --set-active=b >/dev/null 2>&1
timeout 30 $FB flash dtbo_b "$R/out/boot-miro-v33/dtbo.img" >/dev/null 2>&1
log "booting reader"
timeout 60 $FB boot "$R/out/boot-miro-v32/boot.img" >/dev/null 2>&1

IF=""
for i in $(seq 1 70); do
  IF=$(ip -o link 2>/dev/null | grep "02:66:77:88:99:aa" | grep -o "^[0-9]*: [^:@]*" | cut -d' ' -f2)
  [ -n "$IF" ] && break
  sleep 1
done
[ -z "$IF" ] && { log "device NIC never appeared"; exit 1; }
ip addr add 10.42.0.1/24 dev "$IF" 2>/dev/null
ip link set "$IF" up
for i in $(seq 1 30); do $D true 2>/dev/null && break; sleep 1; done
$D true 2>/dev/null || { log "ssh never answered"; exit 1; }
log "reader up on $IF"

# --- channel 1: the MIROLOG2 console ring, last 32 MiB of userdata ------------
# The board's root partition is the GPT entry named "linux" (drivers/MiroUfs
# MiroUfs.cpp: kRootPartition = "linux"); board.toml's [userdata] window points
# at the same physical partition. There is no entry called "userdata".
USERDATA=$($D 'for b in /sys/class/block/*; do grep -qx PARTNAME=linux $b/uevent 2>/dev/null && basename $b; done' 2>/dev/null | head -1)
if [ -n "${USERDATA:-}" ]; then
  log "root partition ($USERDATA, GPT name \"linux\"): reading LBA 128611072+8192"
  $D "dd if=/dev/$USERDATA of=/run/log.bin bs=4096 skip=128611072 count=8192 status=none" 2>/dev/null
  $D "cat /run/log.bin" > "$OUT/$TAG-log.bin" 2>/dev/null
  log "log ring: $(wc -c < "$OUT/$TAG-log.bin") bytes"
  python3 /root/k80pro-port/UniXNU-miro-linux/scripts/parse-mirolog.py \
      "$OUT/$TAG-log.bin" --json-out "$OUT/$TAG-log.json" 2>&1 | head -12
else
  log "root partition (GPT name \"linux\") not found; dumping the inventory:"
  $D 'for b in /sys/class/block/sd*; do n=$(grep -o "PARTNAME=[^ ]*" $b/uevent 2>/dev/null | head -1); sz=$(cat $b/size 2>/dev/null); echo "$(basename $b) ${n:-<no PARTNAME>} ${sz:-?} sectors"; done' 2>/dev/null | head -40 | tee -a /root/k80pro-port/collect3/inventory.txt
  log "  (inventory also in collect3/inventory.txt)"
fi

# --- channel 2: oops partition (probe + panic record) ------------------------
OOPS=$($D 'for b in /sys/class/block/*; do grep -qx PARTNAME=oops $b/uevent 2>/dev/null && basename $b; done' 2>/dev/null | head -1)
if [ -n "${OOPS:-}" ]; then
  $D "dd if=/dev/$OOPS of=/run/oops.bin bs=1M count=16 status=none" 2>/dev/null
  $D "cat /run/oops.bin" > "$OUT/$TAG-oops.bin" 2>/dev/null
  log "oops: $(wc -c < "$OUT/$TAG-oops.bin") bytes"
  python3 /root/k80pro-port/UniXNU-miro-linux/scripts/parse-mirolog.py \
      "$OUT/$TAG-oops.bin" 2>&1 | sed -n '/probe:/,$p' | head -12
fi

$D "reboot -f" 2>/dev/null
log "done"
