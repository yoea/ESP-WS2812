# MSI Mystic Light 主板灯控（纯 Python）

用 Python 直接控制微星主板的 RGB 接口，**不需要 MSI Center，不需要 OpenRGB，零第三方依赖**。

两条路可选：**每灯独立控色**（PC 逐帧推，最灵活）或**控制器内置效果**（40 种，控制器自己跑动画，PC 可退出）。

实测板卡：**MSI MAG B760M MORTAR II（MS-7E13）**
设备：`USB\VID_0DB0&PID_0076`，产品名 `MYSTIC LIGHT`

---

## 为什么不用 OpenRGB

| 版本 | 情况 |
|---|---|
| OpenRGB 0.9（2023） | 根本不认识 `0x0076` 这个 PID，主板灯一个都不显示 |
| OpenRGB 新版 | 会在检测 `MSI Mystic Light Common` 时卡死/闪退 |

根因：这块板用的是**通用 PID `0x0076`**，OpenRGB 有两套检测项都挂在它上面 —— 一套认 usage page `0x0001`，一套认 `0xFF00`。你的设备全部 Feature Report 都在 `0xFF00`，命中的是第二条（日志里显示为 "X870"）。而 OpenRGB 的板卡配置表是按**具体主板的 PID** 查的，`0x0076` 只能退回一个通用配置，实测经常改色无效。

所以直接照协议写脚本最省事。协议来自 OpenRGB 的 `MSIMotherboard185Controller`（GPL-2.0-or-later），由 @t-bond、@CalcProgrammer1、@garashchenko 逆向。

---

## 你的板子属于哪一代协议

枚举 HID 描述符后一目了然：

| Report ID | 长度 | 用途 |
|---|---|---|
| `0x52` | 185 字节 | 区域配置：每个灯区的效果 / 颜色 / 亮度 |
| `0x53` | 725 字节 | **每灯独立控色**：`[0x53, hdr0, hdr1, hdr2, hdr3] + 240 × RGB` |
| `0x80 / 0x81 / 0x82` | 242 字节 | 其他接口（本脚本不用） |
| `0xA0 / 0xA1 / 0xA2` | 761 字节 | 其他接口（本脚本不用） |

Feature Report 上限 761 字节，容易误判成"761 协议"。**判据是 `0x52` 返回 185 字节**，`725 = 5 + 240×3` 才对得上每灯报文。

---

## 本机灯珠配置（实测）

| 接口 | 类型 | 灯珠数 | 走哪条通路 |
|---|---|---|---|
| JARGB1 | 3 针 5V ARGB | **6** | 每灯直控（`0x53`），`--leds1 6` |
| JARGB2 | 3 针 5V ARGB | **12** | 每灯直控（`0x53`），`--leds2 12` |
| JRGB | 4 针 12V RGB | **20**（估算） | 区域路径（`0x52`），整口单色 |

说明：

* **JARGB1 / JARGB2 必须填对颗数**，否则尾部灯珠不亮（6 / 12）。
* JRGB 是 12V 模拟灯带，控制器只给**整口一个颜色**、不区分单颗，所以 **20 颗只作硬件规格记录，协议里不用填**。
* 两个 ARGB 口颗数不同，**不要用 `--leds N`**（它会把所有口统一成一个数），请分别用 `--leds1 6 --leds2 12`。

---

## 用法

```bash
cd "D:\Develope\esp8266\3.WeMOS D1 mini\msi-rgb"

python mystic.py                            # 不带参数 → 控制器内置「rainbow wave」（PC 可退出）
python mystic.py --diag                     # 只看当前状态，不改灯
python mystic.py --list                     # 列出灯区名

# 每灯直控（3 针 ARGB 口）—— 本机 1 口 6 颗、2 口 12 颗
python mystic.py --argb1 FF0000 --leds1 6                        # 1 号口全红（6 颗）
python mystic.py --argb1 FF0000 --argb2 00FF00 --leds1 6 --leds2 12
python mystic.py --argb2 0088FF --leds2 12                       # 2 号口全蓝（12 颗）

# PC 逐帧推的彩虹动画（脚本必须一直开着）
python mystic.py --rainbow-breath --leds1 6    # 彩虹呼吸：色相流动 + 亮度起伏
python mystic.py --rainbow1 --leds1 6          # 静态彩虹渐变（每颗一色，只支持 1 号口）

# 控制器内置效果（效果跑在控制器里，脚本可退出）
python mystic.py --list-effects             # 列出全部 40 个效果
python mystic.py --effect "rainbow wave"    # 彩虹波（推荐）
python mystic.py --effect breathing --speed low --brightness 50
python mystic.py --effect "color wave" --color1 FF0000 --color2 0000FF

# 4 针 12V JRGB 口（整口单色，无需填颗数）
python mystic.py --jrgb FF0000
python mystic.py --zone jrgb1 --color FF0000 --brightness 60

python mystic.py --off                      # 全部关灯，并退出直控模式
```

> **不带参数运行**（`python mystic.py`）＝ 给 JARGB1 + JARGB2 下发**控制器内置的 `rainbow wave`**。
> 好处是**效果跑在控制器里，脚本可以立刻退出，灯效还在**（直到重启或 MSI Center 覆盖）——
> 这是"PC 逐帧推"永远做不到的。JRGB 不动。不写 flash。
>
> 代价是配色由控制器自己生成，做不出"每颗独立 + 呼吸"那种自定义动画。
> 想要那个就用 **`--rainbow-breath`**（PC 逐帧推，20 FPS，脚本必须一直开着，Ctrl+C 退出时熄灯）。

**两种彩虹的区别：**

| | 无参数（内置 `rainbow wave`） | `--rainbow-breath` |
|---|---|---|
| 谁在跑 | 控制器自己 | 电脑逐帧推（20 FPS） |
| 脚本退出后 | **灯效还在** | 灯灭 |
| 可自定义 | 只能选内置效果/速度/亮度 | 色相流动速度、呼吸周期随便调 |
| 带宽 | 一条报文 | 每秒 20 个 `0x53` 包 |
| 切换副作用 | 退出每灯直控模式 | 进直控模式时 `0x52` 会清零 JRGB 的 effect（MSI Center 设过的 JRGB 灯效会被关掉） |

常用参数：

| 参数 | 说明 |
|---|---|
| `--leds1 / --leds2 / --leds3` | 每条 ARGB 口的灯珠数，**必须填对**否则只有前面几颗亮（本机：`6` / `12`） |
| `--leds N` | 把上面三条统一设成 N。**本机两口颗数不同，别用** |
| `--brightness 0-100` | 区域路径静态色 / 内置效果的亮度（0 = 灭）。协议里是 10 档 |
| `--effect NAME` | 用**控制器内置效果**驱动 ARGB 口（见下一节）。不写 `--zone` 时默认作用于 JARGB1+JARGB2 |
| `--rainbow-breath` | PC 逐帧推的彩虹呼吸动画（脚本必须一直开着）。**不带参数时的默认行为是控制器内置的 `rainbow wave`** |
| `--speed low\|medium\|high` | 内置效果的速度（协议里 2 bit，共 3 档） |
| `--color1 / --color2` | 内置效果用到的两个颜色（彩虹类效果忽略它们） |
| `--list-effects` | 列出控制器支持的 40 个内置效果 |
| `--save` | 写进控制器 flash，**重启仍生效**。默认不写，只改内存 |

---

## 控制器内置效果

这是**和"每灯直控"完全不同的另一条路**：把「效果编号」写进 `0x52` 区域报文，**控制器自己跑动画**。
好处是 **PC 端可以完全退出**（每灯直控必须 PC 一直逐帧推，脚本一停灯就定格）；代价是**只能整口一个效果**，不能自定义每颗灯的颜色。

```bash
python mystic.py --list-effects                  # 看全部
python mystic.py --effect "rainbow wave"         # 彩虹波（ARGB 两口都设）
python mystic.py --effect jrainbow --speed high  # ARGB 口专用的彩虹
python mystic.py --effect meteor --speed slow --brightness 70
python mystic.py --zone jargb1 --effect fire     # 只设 1 号口
```

不指定 `--zone` 时，默认作用于 **JARGB1 + JARGB2**，**JRGB 不动**。

### 效果清单（40 个，取自 OpenRGB `MSIMotherboardCommon.h`）

| 值 | 名字（`--effect` 用） | 说明 |
|---|---|---|
| 0x00 | `disable` | 关闭 |
| 0x01 | `static` | 常亮（整口单色） |
| 0x02 | `breathing` | 呼吸 |
| 0x03 | `flashing` | 闪烁 |
| 0x04 | `double flashing` | 双闪 |
| 0x05 | `lightning` | 闪电 |
| 0x06 | `msi marquee` | 跑马灯 |
| 0x07 | `meteor` | 流星 |
| 0x08 | `water drop` | 水滴 |
| 0x09 | `msi rainbow` | 彩虹 A |
| 0x0A | `pop` | 律动 POP |
| 0x0B | `rap` | 律动 RAP |
| 0x0C | `jazz` | 律动 JAZZ |
| 0x0D | `play` | 律动 PLAY |
| 0x0E | `movie` | 影院 |
| 0x0F | `color ring` | 光环 |
| 0x10 | `planetary` | 行星 |
| 0x11 | `double meteor` | 双流星 |
| 0x12 | `energy` | 能量 |
| 0x13 | `blink` | 呼吸灯（快闪） |
| 0x14 | `clock` | 时钟 |
| 0x15 | `color pulse` | 色彩脉动 |
| 0x16 | `color shift` | 色彩偏移 |
| 0x17 | `color wave` | 色彩波浪 |
| 0x18 | `marquee` | 跑马灯（长） |
| 0x19 | `rainbow` | 彩虹 B |
| 0x1A | `rainbow wave` | **彩虹波 ★ 最像"每颗独立彩虹流动"** |
| 0x1B | `visor` | 护目镜 |
| 0x1C | `jrainbow` | **彩虹 · ARGB 口专用 ★** |
| 0x1D | `rainbow flashing` | 彩虹闪烁 |
| 0x1E | `rainbow double flashing` | 彩虹双闪 |
| 0x1F | `random` | 随机 |
| 0x20 | `fan control` | 风扇控制（**非灯效**，别设） |
| 0x21 | `disable2` | 关闭 2 |
| 0x22 | `color ring flashing` | 光环闪烁 |
| 0x23 | `color ring double flashing` | 光环双闪 |
| 0x24 | `stack` | 堆叠 |
| 0x25 | `corsair que` | 海盗船队列 |
| 0x26 | `fire` | 火焰 |
| 0x27 | `lava` | 岩浆 |

名字大小写、空格、下划线、横杠都能混写（`rainbow_wave` = `Rainbow Wave`）。

### 需要知道的几件事

* **彩虹类效果不吃你给的颜色**：`msi rainbow` / `rainbow` / `rainbow wave` / `jrainbow` / `rainbow flashing` / `rainbow double flashing` / `color ring*` / `planetary` / `stack` / `double meteor` 的配色由控制器自己生成，`--color1/--color2` 写了也没用（脚本会提示）。
* **`fire` / `lava` 只有较新的板子支持**，设了没反应属正常。
* **`fan control` 是风扇控制不是灯效**，别误设。
* **音乐律动（`pop`/`rap`/`jazz`/`play`）需要主板有音频输入**，绝大多数板子无效。
* **板子实际支持的是这 40 个的子集**。协议里有不等于你这块 B760M MORTAR II 认。挨个试，能动的就是支持的。
* **默认不写 flash**（`save=0`），重启后恢复 MSI Center 的设定。加 `--save` 才持久化 —— **不建议**，见「已知限制」。
* **MSI Center 在跑的话会覆盖**。

---

## 两条通路

### 1. 区域路径（`0x52`）

两条用途：给 4 针 JRGB 口设色，或者**让控制器自己跑内置效果**（见「控制器内置效果」一节）。
代价是整口共享一个效果，不能自定义每颗灯的颜色。

报文里 18 个灯区记录，各占 10 字节（彩虹区 11 字节，Corsair 区 11 字节但字段排布不同）：

```
偏移    含义
+0      effect   效果编号（见「控制器内置效果」，0x00..0x27）
+1..3   颜色1 RGB
+4      速度(bit0-1) | 亮度(bit2-6) | 同步标志(bit7)
+5..7   颜色2 RGB
+8      bit7 = 使用自定义颜色；bit0-5 = 各灯区的同步标志位
+9      补位（恒 0）
+10     仅彩虹区 / Corsair 区有：cycle_or_led_num（循环数或灯珠数）
```

> 普通灯区记录 10 字节；**彩虹区（JARGB1/2/3）和 Corsair 区是 11 字节**，多出来的第 11 字节在 `+10`。
> 这就是 `ZONE_OFFSET` 里 `0x1F→0x2A`（差 11）而 `0x01→0x0B`（差 10）的原因。

亮度是 **5 位、0..10 档**（`bit2-6`），所以"满亮"就是 `10<<2 = 0x28`。源码里那些 `0x28 / 0x29 / 0x2A` 的魔数就是这么来的（后两个是叠加了速度 1 / 2）。

### 2. 每灯直控（`0x53`）

先发一条 `0x52`「使能报文」把控制器切到直控模式：

* `板载LED0.effect = 0x25`（这就是直控模式标志，回读可以验证）
* 各 ARGB 口的 `cycle_or_led_num` 写灯珠数
* 灯珠 ≤40 时走**单包合并**（`hdr1=6`），>40 时**每条口单独发包**

然后发 `0x53`，头部 `[0x53, 0x25, hdr1, hdr2, 0x00]`：

| 目标 | hdr1 | hdr2 |
|---|---|---|
| 板载 + 同步缓冲 | 6 | 0 |
| JARGB1 | 4 | 0 |
| JARGB2 | 4 | 1 |
| JARGB3 / JCORSAIR | 5 | 0 |

单包合并模式下 240 颗槽位的数据排布（照抄 OpenRGB 的指针运算）：

```
[0 .. 1]        JRGB1, JRGB2（4 针口，各 1 颗）
[2 .. 41]       JARGB1（40 颗）
[42 .. 81]      JARGB2（40 颗）
[82 .. 201]     JCORSAIR（120 颗）
```

> JRGB 虽在「区域路径」那一节，但**直控模式下它由 0x53 包的前 2 个槽位供色**，所以能和 ARGB 一起点。
> 脚本里就是 `apply_argb(..., jrgb=[...])`；不传 `jrgb` 则该口置黑（`--rainbow-breath` 就是不给 JRGB 供色）。

---

## 安全

* **默认 `save_data = 0`** —— 只改控制器内存，**不写 flash**，重启即恢复。想持久化才加 `--save`。
* OpenRGB 源码里标注过 MSI Mystic Light **历史上出过变砖风险**（它能写固件）。本脚本严格照抄 OpenRGB 当前的报文，且默认不提交 flash。
* 跑之前确认 **MSI Center 已退出**（含托盘），否则它会每秒推自己的灯效把设置盖掉。

---

## 已知限制 / 待验证

* **灯珠数要手填**。协议里没有"读回实际灯珠数"的字段，只能按你的风扇规格填。**本机值：JARGB1 = 6、JARGB2 = 12**，已写进脚本默认值，直接 `--argb1 FF0000` 就是对的。填小了尾部不亮，填大了顶多多发些无效数据。
* **`0x80/0x81/0x82` 和 `0xA0/0xA1/0xA2` 这两组报文还没搞清**。它们大概率是固件升级或另一条控制通道，本脚本没碰。
* **JCORSAIR / 第 3 条 ARGB 口**：`0x0076` 的通用配置里只有 2 条 ARGB 口。本机实测确认也只有 **JARGB1 / JARGB2 两条（6 / 12 颗）**，没有第 3 条。
* **直控模式与区域模式互斥（按灯区）**：发过使能报文后灯区进入 `effect=0x25`。`--effect` 会改写该灯区的 effect 字节，等于自动退出那一路的直控；要一起复位用 `--off`。
* **内置效果只覆盖"整口"**：40 个效果里除了彩虹类，其余都只用 `color1/color2` 两个颜色，做不到"每颗灯不同色"这种自由度——那是直控模式的活。

---

## 文件

| 文件 | 说明 |
|---|---|
| `mystic.py` | 控制器本体 + 命令行入口，零依赖 |
| `tools/diag_rgb.py` | 枚举系统里所有 USB/HID 设备（找灯控设备用） |
| `tools/diag_msi_hid.py` | 只读探测微星 HID 设备（已被 `mystic.py --diag` 覆盖） |
| `tools/diag_msi_caps.py` | 枚举 HID 描述符里声明的所有 Feature Report |
