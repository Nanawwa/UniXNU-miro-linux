# AGENTS.md

给在这个仓库里工作的代理的操作说明。完整操作文档在 `docs/READER.md`。

## 用途

无人值守调试环：XNU 崩溃/超时复位回 fastboot → 本 reader 起 Linux 读 `oops` 分区 → 解析 → 回 fastboot。给 UniXNU-miro 的内核迭代提供免拍照的日志通道。

## 铁律（破了就退回"各种卡死"）

1. reader 的 DTBO 必须刷进**当前活动 slot** 的 dtbo 分区（固定 slot B → `dtbo_b`）。`auto.sh` 已含 `--set-active=b` + `flash dtbo_b`。
2. `fastboot boot` 报 `Load Error` → 先 `fastboot --set-active=a` 再 `--set-active=b` 清 `slot-unbootable`。
3. `boot_a`/`boot_b` 头部**保持清零**——这是 1 秒自动回 fastboot 的唯一机制。写回 boot 镜像 = 放弃无人值守。
4. 不写 `userdata`（里面是 iOS 根镜像 / Data 容器）。
5. 设备侧不要跑重 debugfs（`clk_summary` 曾把内核搞崩）。
6. initramfs 有 600 秒看门狗，到点 `reboot -f` 回 fastboot；长任务拆轮。

## 构建（三件套）

1. 内核：pinned linux-piano 树 + `patches/ufs-reader-bringup.patch` + `config/reader.config`，编完 Image 后做**等长** cmdline 替换（`mem_sleep_default=s2idle` → `fw_devlink=permissive`），`mkbootimg` v4 头、4096 页、参数来自 `boot-params.env`。
2. initramfs：`initramfs/` 树 → cpio.gz（busybox + dropbear，密钥在 out/，**不进仓库**）。
3. DTBO：当前工作镜像 v33 的合并配方在 `docs/READER.md` §8.2；合并链的中间产物在工作区，**完整自动化重建脚本待补**（build 脚本丢失，只有文档配方）。rebuild 时先核对产物哈希。

## 不变量

- oops 分区布局（parse-oops.py 与 UniXNU-miro 的 `zzzzzzz-miro-ufs-log.patch` 是一对，两边同步改）：16 MiB = 3968 块 OOPSLOG1 环（248 槽 × 64 KiB）+ 尾部探针 1 块 + panic 记录 8 块（DADAPNC1（沿用历史命名））。
- 设备 IP `10.42.0.2`，主机 `10.42.0.1/24`；netconsole 走 UDP 6666（mini 的 nftables 需放行 USB 子网）。
- 分区定位永远按 `PARTNAME=` 扫 `/sys/class/block/*/uevent`，不要硬编码 sdX。

## 隐私

设备序列号、SSH 私钥、本机绝对路径不进仓库。`README`/`docs` 里的示例路径可以是构建机上的通用位置。
