#!/usr/bin/env python3
"""Print this round's kernel console from the fixed OOPSLOG1 snapshot slot.

The timed-reset thread writes the tail of miro_log_ring into one OOPSLOG1 slot
with sequence 0x4d49524f just before PSCI SYSTEM_RESET. Older OOPSLOG1 slots
carry stale l30-era data, so select by that exact sequence.
"""
import struct
import sys
from pathlib import Path

MAGIC = b"OOPSLOG1"
SEQ = 0x4D49524F
BLOCK = 4096
blob = Path(sys.argv[1]).read_bytes()
hits = []
for off in range(0, len(blob) - BLOCK, BLOCK):
    if blob[off:off + 8] == MAGIC:
        seq, length = struct.unpack_from("<II", blob, off + 8)
        hits.append((off, seq, length))
print("OOPSLOG1 headers: %d" % len(hits), file=sys.stderr)
for off, seq, length in hits:
    if seq == SEQ:
        # native_ufs_oops_log_write puts the header in the first block and the
        # text in the following blocks, not inline after the 24-byte header.
        text = blob[off + BLOCK: off + BLOCK + length].decode("utf-8", "replace")
        print("=== console snapshot at block %d, %d bytes ===" % (off // BLOCK, length))
        for line in text.splitlines():
            line = line.lstrip("D|")
            if line.strip():
                print(line)
        break
else:
    print("no fresh console snapshot found (sequence 0x4d49524f)", file=sys.stderr)
    sys.exit(1)
