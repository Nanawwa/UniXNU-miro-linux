# UniXNU-miro-linux

An unattended debugging reader for the Redmi K80 Pro (`miro`, Qualcomm SM8750). It boots a small mainline Linux over `fastboot boot`, brings up USB networking, reads back the UniXNU kernel's console ring from the `oops` partition over SSH, and returns to the bootloader — so one debugging round needs no key presses and no photographs.

```
fastboot boot xnu-boot.img      UniXNU kernel runs, writes its console ring to the oops partition,
                                then resets (panic handler or the timed autoreset)
   │
   ▼  ABL lands in fastboot on its own (boot partition headers are cleared)
fastboot boot reader-boot.img   mainline Linux 7.2.6 (piano tree), USB-NCM gadget, dropbear
   │
   ▼
auto.sh: wait for the NCM link → ssh 10.42.0.2 → dd 16 MiB from PARTNAME=oops
         → parse (OOPSLOG1 ring + panic record) → reboot -f → next round
```

A round takes about 20 seconds plus the XNU run time.

This repository carries only what the reader adds on top of two upstream projects; it does not vendor their trees.

| Pinned upstream | Revision | Role |
| --- | --- | --- |
| [blu-sharky/linux-piano](https://github.com/blu-sharky/linux-piano) | `453bb567f` (piano-7.2.6) | kernel tree; the K80 Pro DTS lives upstream |
| [blu-sharky/debian-piano](https://github.com/blu-sharky/debian-piano) | `a75f8c5` | rootfs packaging; initramfs layout reference |

## Layout

| Path | Contents |
| --- | --- |
| `patches/ufs-reader-bringup.patch` | kernel changes that make UFS usable: ICE/testbus/ICC/RPMH paths skipped, PHY clocks probed one by one, UFSDBG/PHYDBG traces |
| `config/reader.config` | kernel configuration (UFS PHY and pinctrl built-in, netconsole, initramfs source) |
| `initramfs/` | reader initramfs tree: `beaconinit` entry, USB-NCM setup, dropbear, 600 s watchdog |
| `scripts/auto.sh` | unattended rounds: boot → read → parse → reset |
| `scripts/parse-oops.py` | OOPSLOG1 ring and panic-record decoder |
| `scripts/rescue2.sh`, `scripts/bootwipe.sh`, `scripts/netlog.py` | recovery, boot-header wipe (the auto-return mechanism), netconsole listener |
| `docs/READER.md` | full operational notes: access, oops format, netconsole, rebuild recipes, invariants |
| `boot-params.env` | boot image parameters confirmed against the stock image |

The working reader image (54 MB boot image) and its DTBO are build products; they ship in a GitHub release and are rebuilt from the pinned trees with the recipes in `docs/READER.md`.

## Quick start

```sh
git clone --recurse-submodules https://github.com/blu-sharky/linux-piano
git clone https://github.com/Nanawwa/UniXNU-miro-linux
# build the kernel with config/reader.config, wrap the initramfs, mkbootimg v4
# then:
IMG=/path/to/unixnu-boot.img bash scripts/auto.sh 3
```

Results land in `out/oops-auto-r*.txt` — one parsed console log per round.

## Safety notes

- Everything runs from RAM (`fastboot boot`); nothing is flashed except the reader DTBO into the active slot's `dtbo` partition.
- The auto-return mechanism works by wiping the boot partition headers; restoring Android boot means flashing stock images back (see `docs/READER.md` §10).
- Do not write `userdata`.

## License

GPL-2.0, matching the kernel trees this builds on; see `LICENSE`.
