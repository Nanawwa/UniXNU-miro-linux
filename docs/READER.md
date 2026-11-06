# miro Linux reader — 交接文档（给下一个 agent）

> 本文是 UniXNU-miro-linux 的操作文档，源自构建机上的交接记录，发布前已脱敏。
> `auto.sh` / `rescue2.sh` 等脚本里的工作区路径可用 `READER_BASE` 环境变量覆盖。


生成时间：2026-11-05 · 状态：**已跑通，无人值守可用**
设备：Redmi K80 Pro（codename `miro`，SM8750，BL 已解锁；序列号不进仓库）

---

## 0. 一句话总结

`fastboot boot` 一个自建 Linux（7.2.6，piano 参考树）→ USB-NCM 起网 → SSH 进去 →
从 UFS 的 `oops` 分区 `dd` 出 XNU 内核控制台日志 → 重启后 ABL **1 秒自动回 fastboot**。
主机脚本 `auto.sh` 循环即可，**全程不需要按任何键**。

---

## 1. 拓扑与访问方式

| 角色 | 位置 / 地址 | 说明 |
|---|---|---|
| 设备 | USB 接在 **mini**（不是笔记本） | 序列号不进仓库 |
| mini | `ssh root@<mini>` | 所有构建与刷机都在这里 |
| 设备（Linux 运行时） | `10.42.0.2`，主机侧 `10.42.0.1/24` | USB-NCM，网卡名 `enx0266778899aa` |
| 设备 SSH | `ssh -i /root/k80pro-port/linux-reader/out/reader-ssh-ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@10.42.0.2` | dropbear，口令为空，仅密钥 |

> 设备 MAC：设备侧 `02:11:22:33:44:55`，主机侧 `02:66:77:88:99:aa`（netconsole 目标 MAC 用后者）。

---

## 2. 现成产物

| 文件 | sha256 | 大小 | 说明 |
|---|---|---|---|
| `out/boot-miro-v32/boot.img` | `cc00f0596e2fede73949f30e4674a82a2a09a73574d8aa43d7c1caab2b5b7d84` | 54 MB | reader 内核（内嵌 initramfs） |
| `out/boot-miro-v33/dtbo.img` | `5b05a9cd7489e3330366e9da56902a2733ec5412c33696f48615181027006ca7` | 503 KB | reader 设备树 overlay（**UFS 靠它**） |
| `out/initramfs-reader-v10.cpio.gz` | `d2737ea0e5378b1305431f50da02752bc5012597154ffcaa6164048ec6a815b3` | 13 MB | initramfs（busybox + dropbear + 8080 httpd） |
| `patches/ufs-reader-bringup.patch` | — | 186 行 | 内核补丁（`git diff`），UFS 能起来的关键 |
| `out/reader-ssh-ed25519` | — | — | 设备 SSH 私钥 |

根目录：`/root/k80pro-port/linux-reader/`（下文相对路径都相对它）。

---

## 3. 一键无人值守（最常用）

```bash
bash /root/k80pro-port/linux-reader/auto.sh 3      # 跑 3 轮
```

每轮自动完成：

1. 等 fastboot（正常情况下 **1 秒内**就有）
2. `fastboot --set-active=b` → `fastboot flash dtbo_b out/boot-miro-v33/dtbo.img`
3. `fastboot boot out/boot-miro-v32/boot.img`（RAM 启动，不写分区）
4. 等 `enx*` 网卡 → 配 `10.42.0.1/24`
5. 设备里按 `PARTNAME=oops` 找块设备（当前 `/dev/sda24`）→ `dd` 16 MiB → `/run/oops.bin`
6. `ssh cat /run/oops.bin > out/oops-auto-r<N>.bin`（16,777,216 字节）
7. 调 `planC/parse-oops.py` 生成 `.txt` / `.json`
8. `reboot -f` → ABL 自动回 fastboot → 下一轮

实测 3 轮：每轮约 20 秒，零人工。日志 `auto.log`；产物 `out/oops-auto-r*.bin|.txt|.json`。

**换镜像**（例如换成 XNU）：

```bash
IMG=/path/to/xnu-boot.img bash auto.sh 1
```

---

## 4. 为什么它能自己回 fastboot（核心机制）

`boot_a` 和 `boot_b` 的**头部已被清零**（前 8 KiB 全 0）：

```
sde14 = boot_a, sde49 = boot_b
```

ABL 找不到可引导镜像 → **1 秒内落进 fastboot**。这是目前唯一稳定、无延迟的方案。

> BCB 方案（往 `misc`=`sda12` 写 `bootonce-bootloader`）**实测可用但要 72 秒**，而且
> 有时不生效、退回 Android 空转。**不要依赖 BCB**，`auto.sh` 里也没有用。

---

## 5. 手动读 oops（不走 auto.sh 时）

```bash
KEY=/root/k80pro-port/linux-reader/out/reader-ssh-ed25519
D="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@10.42.0.2"

# 1) 按名字找分区（不要硬编码 sdX，枚举顺序会变）
$D 'for b in /sys/class/block/*; do grep -qx "PARTNAME=oops" $b/uevent 2>/dev/null && basename $b; done'

# 2) 导出
$D 'dd if=/dev/sda24 of=/run/oops.bin bs=1M count=16 status=none; sha256sum /run/oops.bin'

# 3) 拉回
ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    root@10.42.0.2 'cat /run/oops.bin' > /tmp/oops.bin

# 4) 解析
python3 /root/k80pro-port/planC/parse-oops.py /tmp/oops.bin \
        --log-out /tmp/oops.txt --json-out /tmp/oops.json
```

已知分区（仅供参考，**始终按 PARTNAME 扫**）：

| PARTNAME | 设备节点 | 备注 |
|---|---|---|
| `oops` | `/dev/sda24` | 16 MiB，XNU 内核控制台环 + panic 记录 |
| `misc` | `/dev/sda12` | BCB（本机实测全 0，未被 slot 使用） |
| `boot_a` / `boot_b` | `sde14` / `sde49` | **头部已清零** |
| `dtbo_a` / `dtbo_b` | `sde18` / `sde53` | 当前 slot B 生效，dtbo_b 里是 v33 |

### oops 格式（parser 已实现，供判读参考）

```
16 MiB = 4096 块
  头部 3968 块 = OOPSLOG1 环，248 槽 × 64 KiB
    槽头 [0:8]"OOPSLOG1" [8:12]seq [12:16]len [16:20]slot（均 LE）
    槽体 = 块 1..15（≤ 61,440 B）
  尾部 9 块 = 探针 1 块 + DADAPNC1 panic 记录 8 块
判读：取 sequence 最大的若干槽，按 sequence 升序拼接即得日志
```

`parse-oops.py` 输出：`log window` / `sequences` / `probe`（含 `why=` 原因）/
`panic: v1 ... crc=ok` + 还原出的整段控制台日志。

---

## 6. 早期崩溃诊断（UFS / 内核还没起来时）

屏幕（fbcon）不可靠——面板会在崩溃时黑掉。可用通道：

### 6.1 netconsole（推荐）

内核已编入 `CONFIG_NETCONSOLE` / `NETCONSOLE_DYNAMIC` / `NETPOLL`。
init 里**没有**自动挂（挂早了会干扰启动），要在 Linux 起来后手工开：

```bash
# mini 侧先开监听（写 netconsole.log）
tmux new -s nc 'python3 /root/k80pro-port/linux-reader/netlog.py'

# 设备侧（NCM 起来后，约开机 4 秒）
ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@10.42.0.2 '
  mkdir -p /sys/kernel/config/netconsole/t1 && cd /sys/kernel/config/netconsole/t1
  echo usb0              > dev_name
  echo 6666              > local_port
  echo 10.42.0.1         > remote_ip
  echo 6666              > remote_port
  echo 02:66:77:88:99:aa > remote_mac
  echo 1                 > enabled'
```

**前提**：mini 的 nftables 默认 `policy drop`，已加过放行（只放 USB 子网）：

```bash
nft add rule ip filter INPUT ip saddr 10.42.0.0/24 udp dport 6666 accept
```

> 没有这条规则时 `netconsole.log` 会是 0 行——排查时先确认它。
> **不要**跑 `clk_summary` 之类重 debugfs 操作，曾直接把内核搞崩。

### 6.2 源码调试打印

内核树里留了 `UFSDBG:` / `PHYDBG:` 前缀 `pr_info`（见 `patches/ufs-reader-bringup.patch`），
开机 ~12 秒会打一串 UFS 初始化进度，是定位卡点最快的办法。不需要时可删。

---

## 7. 接 XNU 镜像做完整调试环

设备已经永远落 fastboot，所以"跑 XNU → 崩溃 → 自动回 fastboot → Linux 读日志"是闭环：

```bash
# 1) 跑 XNU（RAM 启动，不写分区）
fastboot boot /path/to/unixnu-boot.img

# 2) XNU 崩溃 / 自动 reset 后，ABL 自动回 fastboot（约 1 秒）

# 3) 起 reader 读日志
bash /root/k80pro-port/linux-reader/auto.sh 1
```

多轮自动化：

```bash
for i in 1 2 3; do
  fastboot boot /path/to/unixnu-boot.img
  sleep 120                                   # 等 XNU 跑完 + 崩溃 + reset
  bash /root/k80pro-port/linux-reader/auto.sh 1
done
```

注意：`auto.sh` 每轮都 `flash dtbo_b`——XNU 与 Linux 若需要不同 dtbo，改 `DTBO=` 或去掉那一步。

---

## 8. 重建

### 8.1 内核（v32）

```bash
bash /root/k80pro-port/linux-reader/build-v32.sh
```

做的事：

1. 树 `linux-piano`（blobless，piano-7.2.6 分支），`O=linux-piano/out/reader`
2. 关键 config（已写入 `.config`）：
   - `CONFIG_PHY_QCOM_QMP_UFS=y`（**原本 =m，initramfs 无模块 → UFS PHY 永不 probe**）
   - `CONFIG_PINCTRL_SM8750=y`（同理）
   - `CONFIG_NETCONSOLE=y` / `NETCONSOLE_DYNAMIC=y` / `NETPOLL=y` / `CONFIGFS_FS=y`
   - `CONFIG_INITRAMFS_SOURCE=out/initramfs-reader-v10.cpio.gz`
3. 编完 Image 后**二进制等长替换** cmdline：
   `mem_sleep_default=s2idle` → `fw_devlink=permissive   `
   （脚本里有 python 片段）。运行期实测 cmdline：
   `console=tty0 loglevel=8 fbcon=font:TER16x32 rdinit=/beaconinit pd_ignore_unused clk_ignore_unused fw_devlink=permissive    panic_on_oops=1 panic=-1`
4. `mkbootimg`（v4 头、4096 页；`base/kernel_offset/ramdisk_offset/tags_offset` 取自
   `debian-piano/boot/stock-boot-params.env`）

### 8.2 DTBO（v33）

```bash
bash /root/k80pro-port/linux-reader/build-v33.sh
```

DTBO = stock miro overlay 全部 fragment **+** reader fragment（合并成**单个** overlay，
ABL 只接受一个 dtbo，不能链式）：

1. `gcc@100000` → mainline `qcom,sm8750-gcc`，`#power-domain-cells=<1>`
2. `syscon@1fc0000` → `qcom,sm8750-tcsr` + `#clock-cells=<1>`
3. `mc_virt`(interconnect@1) 及其余 13 个 NoC 全换 `qcom,sm8750-*-noc`，
   `#interconnect-cells=<2>`，`qcom,bcm-voters=<&apps_bcm_voter_ml>`
4. `rsc@16500000` 内新增 `clock-controller-ml`（`qcom,sm8750-rpmh-clk`）+ `bcm-voter-ml`
5. USB：mainline `qcom,snps-dwc3` wrapper + `usb-nop-xceiv`，downstream dwc3 disabled
6. `simple-framebuffer`（1440×3200，stride 5760，a8r8g8b8）+ `stdout-path`
7. UFS 供电：`vdd-hba`/`vcc`/`vccq`/`vdda-phy`/`vdda-pll` 全 `regulator-fixed` always-on
8. UFS 主控：mainline `interconnects`（2 cell）、`power-domains=<&gcc GCC_UFS_PHY_GDSC>`、
   9 个 clocks（`ref_clk` → `&rpmhcc_ml RPMH_LN_BB_CLK3`）
9. UFS PHY：`compatible="qcom,sm8750-qmp-ufs-phy"`，clocks 只留 `ref` + `ref_aux`
   （**`qref` 会挂死总线**），`power-domains=<&gcc GCC_UFS_MEM_PHY_GDSC>`

### 8.3 内核补丁（`patches/ufs-reader-bringup.patch`，2 文件）

`drivers/ufs/host/ufs-qcom.c`：

- `devm_gpiod_get_optional("reset")` 遇 `-EPROBE_DEFER` → warn + 当 NULL 继续（vendor TLMM 绑不上）
- `ufs_qcom_ice_init()` 直接 `return 0`（**一碰 ICE/HWKM 就总线卡死**）
- 跳过 `ufs_qcom_get_default_testbus_cfg()` / `ufs_qcom_testbus_config()`
- 跳过 `ufs_qcom_icc_update_bw()` / `ufs_qcom_icc_set_bw()`（BCM/RPMH 投票会卡）
- `UFSDBG:` 打印

`drivers/phy/qualcomm/phy-qcom-qmp-ufs.c`：

- `clk_bulk_prepare_enable` 改成逐个 `clk_prepare_enable` + `PHYDBG:` 打印

---

## 9. 关键不变量（破坏就会退回"各种卡死"）

1. **reader DTBO 必须刷进当前活动 slot 的 dtbo 分区**（现在固定 slot B → `dtbo_b`）。
   `auto.sh` 已含 `--set-active=b` + `flash dtbo_b`。
2. `fastboot boot` 报 `Load Error` 时，先 `fastboot --set-active=a` 再 `--set-active=b`
   清 `slot-unbootable`（崩溃几次后 ABL 会拉黑槽）。
3. `boot_a/boot_b` 头部保持清零**才**能自动回 fastboot；写回 boot 镜像会失去该能力。
4. 不要写 `userdata`（里面是 iOS 根镜像 / Data 容器）。
5. 不要在设备上跑重 debugfs（`clk_summary` 曾把内核搞崩）。
6. init 里有 **600 秒看门狗**（到点 `busybox reboot -f`）；因为永远回 fastboot，安全，
   但别指望 Linux 会话活过 10 分钟。
7. USB-NCM 网卡名固定 `enx0266778899aa`（MAC 决定），但仍建议按 `enx*` 匹配。

---

## 10. 恢复 / 回滚

### 设备彻底没反应（黑屏、USB 全无）
长按电源 **10–15 秒**强制关机，等 3 秒，按住 **电源 + 音量减** 进 fastboot。

### 自动救援（抓到 fastboot 就切槽 A + 刷回官方 dtbo）
```bash
bash /root/k80pro-port/linux-reader/rescue2.sh     # 0.2 秒轮询；不要用 sleep 1 的旧版
```

### 恢复 Android 引导（以后需要时）
```bash
fastboot flash boot_a /root/k80pro-port/os4pkg/img/boot.img
fastboot flash boot_b /root/k80pro-port/os4pkg/img/boot.img
fastboot flash dtbo_a /root/k80pro-port/os4pkg/img/dtbo.img
fastboot flash dtbo_b /root/k80pro-port/os4pkg/img/dtbo.img
fastboot --set-active=a
```
> 写回 boot 分区后设备**不再自动回 fastboot**，无人值守失效。

---

## 11. 首次读到的 XNU 状态（2026-11-05）

`oops` 里 27 轮、5968 行 / 480 KB：

```
(改名前的日志原样引用，magic 现为 DADAPNC1 / 前缀 miro-) dada crash: launchd pid 6
wait_status 0x1: signalled signal 1 exit -1     ← SIGHUP
csflags 0x22002301 killed 0
panic-on-crash disabled via boot-arg
```

- APFS 能挂到 `DawnUpdate21H461.J120J121J207J208SystemCryptex` 并 `mount-complete`
- 随后 SpringBoard / liveactivitiesd / watchdogd / mobileactivation / PerfPowerService
  反复 `Too many corpses being created`
- 关键报错：
  - `BindFS bindfs_mount: lookup of /private/preboot/.../usr/standalone/firmware failed error: 2`
  - `AMFI: Launch Constraint Violation (not enforcing) ... init_exclavekit`
  - `failed to load virtual random: (-147)`
  - `DT_get_fstab_entries: failed to get filesystem entry at: /filesystems/fstab`

---

## 12. 已知限制

- ICE（内联加密）、testbus、icc 带宽投票、`qref` 时钟、UFS reset-gpio 都被**有意跳过/忽略**：
  裸块读写没问题（oops 已验证），加密/挂起/性能路径未验证。
- `boot_a/boot_b` 已清零（Android 原本就起不来），恢复需刷 stock boot.img。
- UFS 的 PMIC 供电用 fixed regulator（假设 ABL 已上电），没有真正做电压域管理。
- 每轮 ~20 秒，主要耗时是 `fastboot boot` 传输 54 MB 内核。
- Linux 侧 600 秒看门狗会自己重启（→ 回 fastboot），长任务要拆轮。
