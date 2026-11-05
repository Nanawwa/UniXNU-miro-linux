#!/usr/bin/env python3
"""Parse the raw `oops` partition written by the UniXNU-miro kernel's UFS log writer.

  parse-oops.py IMAGE [--log-out FILE] [--json-out FILE] [--self-test]

IMAGE is a raw 16 MiB dump of by-name/oops (or the block device itself).
It understands all three records the driver writes:

  OOPSLOG1  ring at the head of the partition: 3968 blocks = 248 slots,
            each slot 16 blocks (64 KiB). Header block: magic, sequence,
            length, slot (all uint32 LE); body follows in the next 15 blocks.
  DADAPRB1  one probe block at the start of the 9-block tail panic window.
  DADAPNC1  8 blocks of panic text at the very end of the partition.

Layout verified 2026-11-05 against DadaUfs2.cpp lines 1198-1293 and
1453-1561. The panic window starts at partition_last_lba + 1 - 9; the
log window starts at the partition's first block.
"""
import argparse
import json
import struct
import sys
import tempfile
import zlib
from pathlib import Path

BLOCK = 4096
LOG_BLOCKS = 3968
SLOT_BLOCKS = 16
SLOT_COUNT = LOG_BLOCKS // SLOT_BLOCKS
PANIC_RECORD_BLOCKS = 8
PROBE_BLOCKS = 1
PANIC_WINDOW_BLOCKS = PANIC_RECORD_BLOCKS + PROBE_BLOCKS
LOG_MAGIC = b"OOPSLOG1"
PROBE_MAGIC = b"DADAPRB1"
PANIC_MAGIC = b"DADAPNC1"
MAX_LOG_BYTES = (SLOT_BLOCKS - 1) * BLOCK
MAX_PANIC_BYTES = PANIC_RECORD_BLOCKS * BLOCK - 32


def offsets(blob):
    blocks = len(blob) // BLOCK
    if blocks < PANIC_WINDOW_BLOCKS + SLOT_BLOCKS:
        raise ValueError(f"{blocks} blocks is too small for an oops partition")
    window = blocks - PANIC_WINDOW_BLOCKS
    return {
        "blocks": blocks,
        "log_blocks": min(LOG_BLOCKS, window),
        "probe_block": window,
        "panic_first_block": window + PROBE_BLOCKS,
    }


def parse_log(blob, off):
    rounds = []
    for slot in range(min(SLOT_COUNT, off["log_blocks"] // SLOT_BLOCKS)):
        at = slot * SLOT_BLOCKS * BLOCK
        header = blob[at:at + BLOCK]
        if header[:8] != LOG_MAGIC:
            continue
        sequence, length, slot_field = struct.unpack_from("<III", header, 8)
        if length > MAX_LOG_BYTES:
            continue
        body = blob[at + BLOCK:at + BLOCK + length]
        rounds.append({
            "slot": slot,
            "slot_field": slot_field,
            "sequence": sequence,
            "length": length,
            "text": body.decode("utf-8", errors="replace"),
        })
    rounds.sort(key=lambda r: r["sequence"])
    return rounds


def parse_probe(blob, off):
    block = blob[off["probe_block"] * BLOCK:(off["probe_block"] + 1) * BLOCK]
    if block[:8] != PROBE_MAGIC:
        return None
    return {
        "status": struct.unpack_from("<I", block, 8)[0],
        "store_geometry_valid": block[12],
        "log_open": block[13],
        "host_ready": block[14],
        "panic_window_last_lba": struct.unpack_from("<Q", block, 16)[0],
        "why": block[24:88].split(b"\0")[0].decode("utf-8", errors="replace"),
    }


def parse_panic(blob, off):
    at = off["panic_first_block"] * BLOCK
    record = blob[at:at + PANIC_RECORD_BLOCKS * BLOCK]
    if record[:8] != PANIC_MAGIC:
        return None
    version, length, crc, blocks = struct.unpack_from("<IIII", record, 8)
    if version != 1 or length > MAX_PANIC_BYTES:
        return None
    text = record[32:32 + length]
    return {
        "version": version,
        "length": length,
        "crc": crc,
        "crc_ok": (zlib.crc32(text) & 0xFFFFFFFF) == crc,
        "blocks": blocks,
        "text": text.decode("utf-8", errors="replace"),
    }


def report(path, log_out=None, json_out=None):
    blob = path.read_bytes()
    off = offsets(blob)
    rounds = parse_log(blob, off)
    probe = parse_probe(blob, off)
    panic = parse_panic(blob, off)

    print(f"{path}: {off['blocks']} blocks ({len(blob)} bytes)")
    print(f"log window: {off['log_blocks']} blocks, {len(rounds)} valid OOPSLOG1 rounds")
    if rounds:
        print(f"sequences: {rounds[0]['sequence']} .. {rounds[-1]['sequence']}")
    if probe:
        print(f"probe: status=0x{probe['status']:x} store={probe['store_geometry_valid']} "
              f"log={probe['log_open']} host={probe['host_ready']} "
              f"last_lba={probe['panic_window_last_lba']} why={probe['why']!r}")
    else:
        print("probe: none")
    if panic:
        print(f"panic: v{panic['version']} {panic['length']} bytes "
              f"crc={'ok' if panic['crc_ok'] else 'BAD'}")
        print("--- panic text ---")
        print(panic["text"].rstrip("\0"))
    else:
        print("panic: none")

    log_text = "".join(r["text"] for r in rounds)
    if log_out:
        log_out.write_text(log_text, encoding="utf-8")
        print(f"wrote log text to {log_out} ({len(log_text)} bytes)")
    if json_out:
        json_out.write_text(json.dumps({
            "layout": off,
            "rounds": [{k: v for k, v in r.items() if k != "text"} for r in rounds],
            "probe": probe,
            "panic": {k: v for k, v in panic.items() if k != "text"} if panic else None,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"wrote metadata to {json_out}")
    return rounds, probe, panic


def self_test():
    blob = bytearray(16 * 1024 * 1024)
    off = offsets(bytes(blob))
    messages = [
        (7, b"round seven: DADA-DIGEST line one\n"),
        (8, b"round eight: ERROR something failed\n"),
        (9, b"round nine: back to normal\n"),
    ]
    for seq, text in messages:
        slot = seq % SLOT_COUNT
        at = slot * SLOT_BLOCKS * BLOCK
        blob[at:at + 8] = LOG_MAGIC
        struct.pack_into("<III", blob, at + 8, seq, len(text), slot)
        blob[at + BLOCK:at + BLOCK + len(text)] = text

    probe_at = off["probe_block"] * BLOCK
    blob[probe_at:probe_at + 8] = PROBE_MAGIC
    struct.pack_into("<I", blob, probe_at + 8, 0x2A)
    blob[probe_at + 12] = 1
    blob[probe_at + 13] = 1
    blob[probe_at + 14] = 1
    struct.pack_into("<Q", blob, probe_at + 16, 0x123456)
    blob[probe_at + 24:probe_at + 24 + 5] = b"okwhy"

    panic_text = b"panic: vm_shared_region_start_address() failed\n"
    panic_at = off["panic_first_block"] * BLOCK
    blob[panic_at:panic_at + 8] = PANIC_MAGIC
    struct.pack_into("<IIII", blob, panic_at + 8, 1, len(panic_text),
                     zlib.crc32(panic_text) & 0xFFFFFFFF, PANIC_RECORD_BLOCKS)
    blob[panic_at + 32:panic_at + 32 + len(panic_text)] = panic_text

    with tempfile.TemporaryDirectory(prefix="oops-selftest-") as tmp:
        sample = Path(tmp) / "oops.bin"
        sample.write_bytes(blob)
        rounds, probe, panic = report(sample)
        assert [r["sequence"] for r in rounds] == [7, 8, 9], rounds
        assert all(r["slot_field"] == r["slot"] for r in rounds)
        assert "round eight" in rounds[1]["text"]
        assert probe and probe["status"] == 0x2A and probe["why"] == "okwhy"
        assert probe["panic_window_last_lba"] == 0x123456
        assert panic and panic["crc_ok"] and "vm_shared_region" in panic["text"]
    print("self-test: OK")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image", type=Path, nargs="?", help="raw oops partition dump")
    parser.add_argument("--log-out", type=Path, help="write concatenated OOPSLOG1 text here")
    parser.add_argument("--json-out", type=Path, help="write metadata as JSON here")
    parser.add_argument("--self-test", action="store_true", help="synthesize a sample image and verify all parsers")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.image:
        parser.error("IMAGE is required unless --self-test is used")
    report(args.image, args.log_out, args.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
