#!/bin/bash
set -u
R=${READER_BASE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
FB=/usr/bin/fastboot
KEY=$R/out/reader-ssh-ed25519
LOG=$R/bootwipe.log
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes -o LogLevel=ERROR -o ConnectTimeout=6 root@10.42.0.2"
log(){ echo "[$(date -u '+%H:%M:%S')] $*" | tee -a "$LOG"; }
: > "$LOG"
log "fastboot -> set slot b, flash v33 dtbo, boot v32"
timeout 8 $FB --set-active=a >/dev/null 2>&1
timeout 8 $FB --set-active=b >/dev/null 2>&1
timeout 30 $FB flash dtbo_b $R/out/boot-miro-v33/dtbo.img 2>&1 | grep -E 'Writing|FAILED' | tee -a "$LOG"
timeout 25 $FB boot $R/out/boot-miro-v32/boot.img 2>&1 | tail -1 | tee -a "$LOG"
I=""
for i in $(seq 1 400); do for n in $(ls /sys/class/net 2>/dev/null); do case "$n" in enx*) I=$n;; esac; done; [ -n "$I" ] && break; sleep 0.1; done
[ -z "$I" ] && { log "no NCM"; exit 5; }
ip link set $I up; ip addr replace 10.42.0.1/24 dev $I >/dev/null 2>&1
log "NCM up; wiping boot slot headers"
timeout 30 $SSH '
BA=$(for b in /sys/class/block/*; do grep -qx "PARTNAME=boot_a" $b/uevent 2>/dev/null && basename $b; done | head -1)
BB=$(for b in /sys/class/block/*; do grep -qx "PARTNAME=boot_b" $b/uevent 2>/dev/null && basename $b; done | head -1)
MI=$(for b in /sys/class/block/*; do grep -qx "PARTNAME=misc" $b/uevent 2>/dev/null && basename $b; done | head -1)
echo "boot_a=/dev/$BA boot_b=/dev/$BB misc=/dev/$MI"
dd if=/dev/zero of=/dev/$BA bs=4096 count=2 conv=notrunc status=none && echo "wiped boot_a"
dd if=/dev/zero of=/dev/$BB bs=4096 count=2 conv=notrunc status=none && echo "wiped boot_b"
printf "bootonce-bootloader\0\0\0\0\0\0\0\0\0\0\0\0" | dd of=/dev/$MI bs=1 count=32 conv=notrunc status=none && echo "bcb armed"
sync; echo synced
' 2>&1 | tee -a "$LOG"
log "reboot; waiting up to 240 s for fastboot"
timeout 8 $SSH 'busybox reboot -f' >/dev/null 2>&1 || true
for i in $(seq 1 240); do
  timeout 2 $FB devices 2>/dev/null | grep -q fastboot && { log "FASTBOOT after ${i}s — boot-slot wipe works"; exit 0; }
  sleep 1
done
log "no fastboot within 240 s"
