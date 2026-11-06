#!/usr/bin/env python3
"""Read the MIROLOG2 crash-log format the kernel's BootLog.c actually writes.

The existing parse-oops.py understands OOPSLOG1, the format DadaUfs2.cpp used
before the rename. BootLog.c writes something different, so every collection
reported "32 rounds" of stale data and the real rounds were invisible.

Format (all little endian, 4096-byte blocks):

  block 0            header
    0   char[8]      "MIROLOG2"
    8   u32          version
    12  u32          header_bytes
    16  u64          boot_id
    24  u64          first_lba
    32  u32          window_blocks
    36  u32          msg_first
    40  u32          msg_blocks
    44  u32          msg_bytes
    48  u32          slot_first
    52  u32          slot_blocks
    56  u32          slot_count
    60  u32          slots_written
    64  u32          rounds
    68  u32          uptime_s
    72  u32          state
    76  u32          write_errors
    ...  char[]       tag

  blocks msg_first .. msg_first+msg_blocks-1   kernel message buffer snapshot
  block  slot_first + i*slot_blocks            slot i: compose() text, NUL padded

The struct above mirrors struct boot_log_header in package/BootLog.c; python
sees the same field order because there is no padding between u32 fields and
the u64 fields stay 8-byte aligned.
"""
import argparse
import struct
import sys
import zlib
from pathlib import Path

BLOCK = 4096
HEADER_MAGIC = b"MIROLOG2"
PROBE_MAGIC = b"DADAPRB1"
PANIC_MAGIC = b"DADAPNC1"
PANIC_RECORD_BLOCKS = 8
PROBE_BLOCKS = 1
PANIC_WINDOW_BLOCKS = PANIC_RECORD_BLOCKS + PROBE_BLOCKS

HEADER = struct.Struct("<8sIIQQIIIIIIIIIII")


def parse_header(blob):
    if len(blob) < BLOCK:
        return None
    h = blob[:BLOCK]
    if h[:8] != HEADER_MAGIC:
        return None
    (magic, version, header_bytes, boot_id, first_lba, window_blocks,
     msg_first, msg_blocks, msg_bytes, slot_first, slot_blocks, slot_count,
     slots_written, rounds, uptime_s, state, write_errors) = HEADER.unpack_from(h, 0)
    return {
        "version": version,
        "header_bytes": header_bytes,
        "boot_id": boot_id,
        "first_lba": first_lba,
        "window_blocks": window_blocks,
        "msg_first": msg_first,
        "msg_blocks": msg_blocks,
        "msg_bytes": msg_bytes,
        "slot_first": slot_first,
        "slot_blocks": slot_blocks,
        "slot_count": slot_count,
        "slots_written": slots_written,
        "rounds": rounds,
        "uptime_s": uptime_s,
        "state": state,
        "write_errors": write_errors,
        "tag": h[80:112].split(b"\0")[0].decode("utf-8", "replace"),
    }


def parse_msgbuf(blob, hdr):
    first = hdr["msg_first"] * BLOCK
    count = hdr["msg_blocks"] * BLOCK
    raw = blob[first:first + count]
    n = min(hdr["msg_bytes"], len(raw))
    return raw[:n].decode("utf-8", "replace")


def parse_slots(blob, hdr):
    """Return slots in write order (oldest first) by rotating on slots_written."""
    out = []
    total = hdr["slot_count"]
    written = hdr["slots_written"]
    for k in range(total):
        idx = (written + k) % total          # oldest still-valid slot first
        at = (hdr["slot_first"] + idx * hdr["slot_blocks"]) * BLOCK
        size = hdr["slot_blocks"] * BLOCK
        raw = blob[at:at + size]
        if not raw:
            continue
        text = raw.split(b"\0")[0]
        if not text.strip():
            continue
        out.append({"slot": idx, "ordinal": k, "text": text.decode("utf-8", "replace")})
    return out


def parse_probe(blob):
    # the probe lives at the start of the 9-block tail window
    blocks = len(blob) // BLOCK
    at = (blocks - PANIC_WINDOW_BLOCKS) * BLOCK
    block = blob[at:at + BLOCK]
    if block[:8] != PROBE_MAGIC:
        return None
    return {
        "status": struct.unpack_from("<I", block, 8)[0],
        "store_geometry_valid": block[12],
        "log_open": block[13],
        "host_ready": block[14],
        "why": block[24:88].split(b"\0")[0].decode("utf-8", "replace"),
    }


def parse_panic(blob):
    blocks = len(blob) // BLOCK
    at = (blocks - PANIC_RECORD_BLOCKS) * BLOCK
    rec = blob[at:at + PANIC_RECORD_BLOCKS * BLOCK]
    if rec[:8] != PANIC_MAGIC:
        return None
    version, length, crc, nblocks = struct.unpack_from("<IIII", rec, 8)
    text = rec[32:32 + length]
    return {
        "version": version,
        "length": length,
        "crc_ok": (zlib.crc32(text) & 0xFFFFFFFF) == crc,
        "blocks": nblocks,
        "text": text.decode("utf-8", "replace"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--json-out")
    ap.add_argument("--dump-slots", action="store_true",
                    help="print every slot's text")
    args = ap.parse_args()

    blob = Path(args.image).read_bytes()
    hdr = parse_header(blob)
    probe = parse_probe(blob)
    panic = parse_panic(blob)

    print(f"{args.image}: {len(blob)} bytes ({len(blob)//BLOCK} blocks)")

    if hdr:
        print(f"MIROLOG2 header: boot_id={hdr['boot_id']} tag={hdr['tag']!r}")
        print(f"  rounds={hdr['rounds']} slots_written={hdr['slots_written']}"
              f"/{hdr['slot_count']} uptime={hdr['uptime_s']}s state={hdr['state']}"
              f" errors={hdr['write_errors']}")
        msgbuf = parse_msgbuf(blob, hdr)
        print(f"  kernel message buffer: {len(msgbuf)} bytes")
        slots = parse_slots(blob, hdr)
        print(f"  slots with content: {len(slots)}")
        if args.dump_slots:
            for s in slots:
                print(f"\n===== slot {s['slot']} (ordinal {s['ordinal']}) =====")
                print(s["text"])
        if args.json_out:
            import json
            Path(args.json_out).write_text(json.dumps(
                {"header": hdr, "msgbuf": msgbuf, "slots": slots,
                 "probe": probe, "panic": panic}, indent=1))
            print(f"  wrote {args.json_out}")
    else:
        print("no MIROLOG2 header at block 0")

    if probe:
        print(f"probe: status={probe['status']:#x} why={probe['why']!r} "
              f"store={probe['store_geometry_valid']} log={probe['log_open']} "
              f"host={probe['host_ready']}")
    else:
        print("probe: absent")

    if panic:
        print(f"panic: v{panic['version']} {panic['length']} bytes "
              f"crc={'ok' if panic['crc_ok'] else 'BAD'}")
        print("--- panic text ---")
        print(panic["text"])
    else:
        print("panic: absent")


if __name__ == "__main__":
    main()
