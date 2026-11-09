#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WeMOS D1 mini 60 颗音乐电平灯带 —— 唯一控制脚本（一个进程 / 一个自启任务 / 一个串口）

★ 源自 ESP-WS2812/host/led_host.py @ 19973c3 的 fork，现在只维护这一份。
  只管一条 60 颗灯带（v6 固件，50Hz / 185B 逐颗独立控色帧）。
  板子：WeMOS D1 mini（数据脚 D2/GPIO4），固件就是本目录的 ESP-WS2812.ino，
  型号字符串 "D1MINI-LED60"。历史上还用过 ESP-01S（型号 "ESP01S-LED60"，
  数据脚 GPIO0），协议完全一致所以 DEVICE_MODELS 里仍然兼容它，但板子与固件
  已归档到 ../ESP-01S-LightStrip-60/，不再维护。
  串口既不写死也不靠「谁先枚举到」：逐个端口发握手帧，靠固件自报的
  「型号 + 芯片序列号」认灯带。首次连接时把序列号记进 host/device.json
  （只有一台就自动记住，多台会问你要哪台），以后只认这一个序列号 ——
  换 USB 口按序列号重新定位，同时插着好几块同型号板也只会控制绑定的那一台，
  插的要是别的板子则明确报「绑定的设备不在场」而不去接管。
  曾经接过第二条 8 颗灯带做系统监控，现已拔掉：第二串口 / 采集线程 / 相关参数
  全部从运行代码里删除，历史实现见 git（03821b3 及之前）。
  **开机自启任务只有这一个**。旧的「ESP-WS2812 音乐封面呼吸灯」任务已删除，
  旧 led_host.py 保留在 git 里仅作留档。
  本副本相对原脚本的改动清单：
    - 不指定 --port：按 device.json 的序列号自动认灯带（v6 身份握手）；
      --list-devices 看扫描结果 / --select-device 换一台 / --forget-device 清绑定
    - TASK_NAME / VBS 名换成独立名字
    - LED_COUNT 8 -> 60（逐颗独立控色；v5 固件每颗单独 setPixelColor）
    - FRAME_HZ 100 -> 50（185B/帧 = 92.5kbit/s，占 115200 的 80.3%）
    - RENDER_LEVEL_ATTACK_TAU 0.010 -> 0.020 -> 0.010（60 级精度优先，让瞬态打得到高档）
    - --render-attack/--render-release 现在放歌与麦克风 VU 共用（快起慢落 10/90ms）
    - 电平/颜色平滑 35ms -> 12ms；去掉渐入迟滞与「最后一颗延后」，严格 60 级档位
    - 封面取色重写：细列加权平均 + 三角核平滑，60 颗连续渐变；
      去黑回填改左右邻居插值；weight 布局改色标插值渐变
    - 固件版本 v5；全局亮度由固件硬限 128/255 = 50%，host 侧不额外打折

三件事，按优先级（**麦克风 > 放歌 > 环境彩虹 > 全灭**）：
  1. 麦克风被占用（通话 / 录音 / 开麦）—— 板载 LED 常亮，音量同时决定亮几颗
     （1~60，从最近端往最远端）、颜色（绿 -> 黄 -> 橙 -> 红）和亮度
     （约 1% -> 80% 最终 PWM 占空比）。颜色沿亮起顺序**逐颗连续插值**
     （60 段、每段约 2°），不是四五段硬分段；门限刚过的底噪级别约 1 颗，
     lv=1.0 才刚好亮满 60 颗，真静音一颗不亮。
     **优先级高于放歌**：麦克风在用是「状态提示」，封面配色只是氛围灯；
     直播 / K 歌 / 游戏语音同时放背景音乐时也让电平表顶上来。
     ⚠️ 代价：常驻占麦的 App（Discord / 会议软件 / 挂着麦克风权限的浏览器）
     会让封面灯效长期不出现，放歌不显示封面时先跑 --diagnose 查占用来源。
  2. 有音乐在播、麦克风没占用 —— 认出系统里正在播放的音乐，把专辑封面采成
     60 颗**连续渐变**的配色铺到灯带上（细列加权平均 + 三角核平滑，
     相邻组共享大半像素）；**亮几颗 / 多亮由默认输出设备的实时峰值决定**
     （读的是系统播放混音，不是麦克风）。采样到的黑色不会分给灯珠，
     改用左右邻居的插值色回填，不打断渐变。真静音（peak 约 0）一颗都不亮，
     极小声从 1% 亮度起步。输出端点读不到峰值时才降级回整条呼吸。
  3. 没有 SMTC 曲目、麦克风也没占用（打游戏 / 系统音效）—— **环境彩虹**：
     固定 300° 色相渐变的 60 段彩虹，**默认全灭**；亮几颗、多亮完全照放歌那套
     （同一条 render_led_count 幂曲线 + vu_steps 渐入 + 快起慢落 10/90ms +
     亮度 120ms 低通），只是把封面色换成彩虹色，手感与放歌一致。
     用慢落之后的 value 判静音，声音断续不会闪灭；完全静音全灭，
     输出端点读不到时退回全灭。
「谁在用」读 Windows 隐私同意记录（ConsentStore 下 microphone 键的
LastUsedTimeStart / LastUsedTimeStop），带去抖滤掉输入法那种几十毫秒的短脉冲；
「声音多大」分两路，都是 WASAPI 的 IAudioMeterInformation 设备峰值，
**只读 meter、不打开任何捕获流**，所以不会把自己写进注册表把判定污染成永远在用：
  - 放歌时读默认输出端点 (eRender/eConsole)：系统播放混音峰值，戴耳机也照样有值；
  - 麦克风 VU 读默认输入端点 (eCapture/eMultimedia)：需要别的应用占着麦克风。
同一份 ctypes COM 代码，只是 GetDefaultAudioEndpoint 的参数不同。零第三方依赖，渲染 50Hz。

降级路径的封面呼吸受 MAX_LEVEL = 0.70（--max-level）限制，在 gamma 之前乘到每颗灯上。
两种声音驱动灯效是例外：亮度 raw 直出不过 gamma（1% 过 gamma 会全黑），
放歌先把封面色过 gamma 再乘亮度曲线（1%→100%，满档白色封面发 255/255），
VU 峰值 80%。host 端不再做亮度打折，唯一的硬限是 v5 固件的 128（50%）：
host 发 255 -> 实际 128/255 占空比。

板载 LED（GPIO2 / D4）现在兼两职：
    常驻状态 —— 麦克风没占用 = 熄灭（待机静默）；麦克风占用 = 常亮
    事件脉冲 —— 切歌闪 2 下 / 封面就绪闪 1 下 / 状态切换闪 3 下
                （脉冲优先，闪完回到常驻状态；封面只在明显滞后于切歌时才单独报）
主机失联（关机 / 拔 USB / 后台服务崩）由固件自己判断：3 秒没数据又没收到 OFF
就转成温柔呼吸（PWM 渐亮渐暗，2.6s 一个来回）—— 那时候串口已经断了，
这台电脑发不出任何命令，只能由固件自己接管。加 --no-status-led 可整块关掉。

开关机不是靠「监听 Windows 事件」：后台 pythonw 收不到可靠的关机通知，
Windows 会直接杀进程，finally 里的 OFF 根本发不出去；而且多数主板 USB 在
S5 仍供电，固件不重启、pixels 里留着关机前最后一帧。所以走 fail-safe：
  - 固件：上电先 clear；CMD_BRIGHTNESS 也先 clear 再 show，亮度帧永远不点亮旧数据
  - host：启动 / 重连的第一条指令都是 blank()
          （OFF + 全灭 SET_ALL），再发亮度；重连后把颜色平滑状态一并清零
  - 自启后 BOOT_QUIET_SEC=12s 强制全灭，ambient 另需连续 0.4s 有声才起灯，
          挡住登录音 / 通知音 / 端点刚枚举的毛刺；前台手动跑不启用
这样没人推 SET_ALL 时灯带一定是黑的，不依赖关机那一刻挤出一条 OFF。

空闲时灯带默认全灭，但可以用**控制面板主动换模式**：进程内起一个 HTTP 线程绑
0.0.0.0:51876，浏览器打开 http://<本机IP>:51876/esp60led 即可（根路径和任何
其它路径一律 404，这就是鉴权，别把它暴露到公网）。12 种模式：auto / off /
彩虹流动 / 呼吸灯 / 纯色常亮 / 彗星拖尾 / 亮度波浪 / 跑马灯 / 火焰 / 极光 /
星空 / 静态渐变。选择写入 host/idle_state.json，重启保持；外部直接编辑该文件
也生效（0.5s 轮询 mtime）。三种语义：
  auto = 原有灯效（放歌封面 / 麦克风电平 / 无 SMTC 有声时彩虹电平 / 空闲全灭）；
  off  = 整条永远不亮，覆盖一切；
  其余 10 种 = 强制常亮，不管放歌 / 麦克风 / 游戏 / 开机静默期都不让位。
装饰帧 raw 直出 0~255 全范围，**亮度上限只在固件做一次**（v5 的
BRIGHTNESS_CAP=128 / setBrightness 50%），host 不再二次打折，否则两道相乘
会把颜色压到 24/255、呼吸和波浪的明暗也看不见。装饰帧的颜色与亮度线性相乘，
不放大也不改色相。加 --no-panel 可关掉面板。
10 种装饰模式右上角都有设置点：6 种可调颜色（预设 / 色轮 / Hex）+ 强度，
另外 4 种只调强度；强度默认 50%，按模式独立存 idle_state.json。

（曾经试过「没播音乐时跟屏幕画面走」的抓屏氛围光，因为独占全屏的游戏抓不到画面、
且 GDI 回读整屏要 16ms/次太耗资源，已经移除，不再包含在本文件里。）

用法：
    python led_host_60.py --list-ports              # 看系统串口号（不握手，最快）
    python led_host_60.py --list-devices            # 扫描并认出哪几台是本项目灯带（含序列号）
    python led_host_60.py --select-device           # 多台时重新选一台并记住（也可 --select-device COM7）
    python led_host_60.py --forget-device           # 忘掉绑定，下次启动重新询问
    python led_host_60.py --diagnose                # 体检媒体源 + 麦克风占用，不点亮
    python led_host_60.py --demo                    # 灯带自检（红绿蓝白/扫描/彩虹/呼吸）
    python led_host_60.py                           # 默认：跟随媒体封面呼吸
    python led_host_60.py --app-filter cloudmusic.exe   # 只认网易云，别的播放器不来抢灯
    python led_host_60.py --cover-layout weight     # 按配色权重铺（默认 spatial 左右对应封面）

开机自启 / 后台常驻（Windows）：
    python led_host_60.py --autostart install       # 装好：以后一登录就自动在后台跑（会弹一次 UAC）
    python led_host_60.py --autostart status        # 看有没有在跑、什么时候跑的、日志在哪
    python led_host_60.py --autostart stop          # 临时停掉（不卸，下次登录还会起来）
    python led_host_60.py --autostart start         # 立刻启动一次
    python led_host_60.py --autostart remove        # 彻底卸掉自启

常用参数：
    --port COM7              临时指定首选串口；不写=按 device.json 绑定的序列号自动找
    --list-devices           扫描并列出所有能认出的灯带 + 当前绑定
    --select-device [COM7]   重新绑定要控制的那一台（不带值=扫描后询问）
    --forget-device          清除绑定（删 device.json）
    --panel-port 51876       控制面板端口（局域网可访问，仅 /esp60led 有效）
    --no-panel               关掉控制面板，只能用 host/idle_state.json 切模式
    --idle-mode auto         空闲模式初值；12 种，见控制面板 / README
    --max-level 0.70         封面呼吸灯珠最大亮度 0~1（默认 0.70）
    --brightness 255         固件侧二次亮度（默认满档，一般不改）
    --breathe-period 4.0     呼吸周期（秒），越小呼吸越快
    --breathe-depth 0.40     呼吸幅度 0~1，越大明暗差别越明显
    --no-mic                 关掉麦克风指示与最高优先级抢占（常驻占麦压住封面时用）
    --mic-reverse            翻转电平条点亮方向（默认从离板子最近的灯开始）
    --mic-full-peak 1.00     麦克风 VU 满档对应的输入峰值（默认吃满 0~1 量程）
    --mic-calibrate          采样 5 秒输入峰值，帮你校准 --mic-full-peak
    --render-full-peak 1.00  放歌时输出峰值满档值（灯太暗调小，太容易满档调大）
    --render-calibrate       播放一首歌采样 5 秒，给 --render-full-peak 建议
    --render-attack 0.010    声音电平上升时间常数秒（快起；放歌 + 麦克风 VU 共用）
    --render-release 0.090   声音电平下降时间常数秒（慢落；放歌 + 麦克风 VU 共用）
    --no-status-led          不用板载 LED(GPIO2/D4)做状态指示和事件提示
    --no-ui                  不画终端面板（后台运行时自动生效）
    --background             后台模式：静默运行 + 日志写 logs/led_host.log（自启时用）

依赖见 requirements.txt。Ctrl+C 退出，退出前自动熄灯。

文件内部分区：媒体采集（SMTC + 封面配色） → 麦克风占用/电平 → 终端面板 → 串口输出 → 主控 → 入口。
"""

import argparse
import asyncio
import colorsys
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import unicodedata

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("缺少 pyserial，请先安装： pip install pyserial")
    sys.exit(1)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ============================================================
# 媒体：SMTC（系统媒体传输控制）+ 封面配色
# ============================================================

# 两套 WinRT 绑定都支持，优先用新版：
#   - winrt-*   ：PyWinRT 现在的形态，按命名空间拆包，持续维护，支持新版本 Python
#   - winsdk    ：已废弃，最后版 1.0.0b10(2023-08) 只支持到 Python 3.12，3.14 上装不了
MEDIA_BACKEND = None
try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _MediaManager,
    )
    from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions
    MEDIA_BACKEND = "winrt"
except ImportError:
    try:
        from winsdk.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as _MediaManager,
        )
        from winsdk.windows.storage.streams import Buffer, DataReader, InputStreamOptions
        MEDIA_BACKEND = "winsdk"
    except ImportError:
        pass

try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

HAS_MEDIA = MEDIA_BACKEND is not None and HAS_PILLOW

# 物理灯珠数 = 电脑发来的颜色数：v5 固件逐颗独立控色，不再做「每组复制 2 颗」。
# 帧 payload = 60*3 = 180B，帧长 185B；50Hz 下占 115200 的 80.3%。
# 颗数曲线 / 封面取色 / 面板 / demo 全都按"组"算，别直接写 60。
LED_COUNT = 60


# 九宫格位置权重：中心是画面主体，权重最高；四角最次要
GRID_WEIGHT = ((0.8, 1.1, 0.8),
               (1.1, 1.8, 1.1),
               (0.8, 1.1, 0.8))

# ---- 去黑回填：60 颗灯里不允许出现黑色 ----
# 判据放在「最终 PWM 域」而不是颜色名上：_normalize_values 会把纯黑抬成
# (38,38,38) 的灰，看着不是黑，过 gamma 却只剩 (1,1,1)，肉眼就是黑灯。
# 加饱和度条件是为了保住深蓝这类暗彩色（(20,30,60) gamma 后最大通道只有 4，
# 但 s≈0.67）—— 它有色相，配合色相保底仍看得见，不该被当成黑替换掉。
DARK_MAX_GAMMA = 8           # gamma 后最大通道低于此值才算「太暗」
DARK_MAX_SAT = 0.30          # 且饱和度低于此值才算「没有色相的黑白灰」
DARK_FALLBACK_VALUE = 0.35   # 整张封面全黑时，保留色相把明度提到这个值

# ---- 封面渐变采样：60 颗颜色之间要连续过渡，不能一格一格硬跳 ----
# 旧做法：每条列独立量化取「主色」。主色是离散簇，相邻两列很容易选中不同的簇，
# 8 组时还能凑合，60 颗上就是一排硬边界；再被去黑回填轮换取色一搅，更碎。
# 新做法：细列加权平均 -> 三角核滑动平滑 -> 组内降采样 -> 明度归一化。
# 相邻组共享大半像素，颜色差被自然压住，得到一条连续渐变；
# 同时仍保留「灯带左 = 封面左」的空间对应，不是把整张图糊成一个色。
COVER_OVERSAMPLE = 8          # 每颗先采 8 条细列（60 颗 = 480 条）
COVER_SMOOTH_GROUPS = 3.0     # 三角核半径，单位「组」；0=不平滑，越大越糊。
                              # 3 组 = 一个硬边界摊到约 6 组(12 颗灯)，
                              # 实测红->黑带->蓝的极端封面单步从 101 降到 56。
COVER_FINAL_SMOOTH = 1        # 明度归一化后再抹一遍的单位（组），消掉 gamma /
                              # v_floor 引入的折点；实测单步再降 56 -> 52。
COVER_SAMPLE_HEIGHT = 48      # 细采样图像高度，控制切歌时的计算量


def analyze_cover(img_bytes: bytes, top: int = 10):
    """
    封面 -> 带权重的多色配色。

    做法：切成 3x3 九宫格（比整图取单色准得多，能同时拿到主体色和背景色），
    每格各自量化取色，按「像素占比 × 饱和度 × 位置权重」打分；
    再按色相/明度相近原则合并同色系，累加权重；最后取 top N 并归一化。

    返回 [(rgb, weight), ...]，按权重降序，weight 之和为 1。
    最多取 top=10 色：60 颗灯带的 weight 布局拿它当插值色标，色标越多渐变越细；
    封面本身颜色少时自然少于 10 色，不凭空补重复色。
    """
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img = img.resize((96, 96), Image.BILINEAR)

    merged = {}          # key -> [score, 加权色值和, 权重和]
    for gy in range(3):
        for gx in range(3):
            block = img.crop((gx * 32, gy * 32, (gx + 1) * 32, (gy + 1) * 32))
            q = block.quantize(colors=6, method=Image.MEDIANCUT)
            palette = q.getpalette()
            w = GRID_WEIGHT[gy][gx]
            for count, idx in q.getcolors():
                r, g, b = palette[idx * 3:idx * 3 + 3]
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                if v < 0.02:                                  # 真正的纯黑才丢，其余暗部要保留
                    continue
                # 明度是第三个维度：暗区权重适度降低但不清零，黑色仍会进入配色候选，
                # 免得"黑色很多的封面"一点暗部都没有；发灯前 fill_dark_leds() 会用
                # 左右邻居的插值色填掉黑位，所以灯带上不会出现黑灯、渐变也不断。
                # 饱和度只做【轻微】加权（0.65~1.0）：早期用 (0.35+0.65*s) 惩罚太重，
                # 大块白色(s=0)的权重只剩彩色的 35%，压不住反而被小面积彩色抢走。
                score = count * w * (0.65 + 0.35 * s) * (0.40 + 0.60 * v)
                # 按 HSV 分桶合并（色相 30° 一档）：用 RGB 量化会把同一色系的
                # 深浅变化当成不同颜色，导致配出来的几色几乎没差别
                key = (int(h * 12), min(2, int(s * 3)), min(2, int(v * 3)))
                slot = merged.setdefault(key, [0.0, [0.0, 0.0, 0.0], 0.0])
                slot[0] += score
                slot[1][0] += r * score
                slot[1][1] += g * score
                slot[1][2] += b * score
                slot[2] += score

    if not merged:
        return []

    items = []
    for score, acc, wsum in merged.values():
        rgb = tuple(round(c / wsum) for c in acc)
        items.append((rgb, score))
    items.sort(key=lambda x: -x[1])

    items = items[:top]
    total = sum(s for _, s in items) or 1.0
    colors = _normalize_values([rgb for rgb, _ in items])
    return [(c, s / total) for (rgb, s), c in zip(items, colors)]


def _normalize_values(colors, v_gamma=0.70, v_target=0.75, v_floor=0.15):
    """
    明度处理，两个原则：

    1. sat_min 必须是 0。给饱和度设下限会把白色(s=0)和黑白灰硬染成彩色，
       而灰度的色相恰好是 0（红），结果就是"大块白色变成红橙"。
       黑白封面就该只有黑白，靠明度出层次。

    2. 用 gamma 提亮，不要用 min-max 归一化。后者会把"最暗的那色"强行拉到某个下限，
       于是白底上的一块亮红（v=0.90）会因为白色 v=1.0 而被当成"最暗"，压成暗红。
       gamma 只抬暗部、几乎不动亮部，绝对亮度关系得以保留。

    整体偏暗的封面（最亮色仍 < v_target）再统一增益，避免灯几乎不亮。
    """
    hsv = [colorsys.rgb_to_hsv(*[c / 255 for c in c]) for c in colors]
    vs = [v ** v_gamma for _, _, v in hsv]
    vmax = max(vs) if vs else 0.0
    if 0 < vmax < v_target:
        gain = v_target / vmax
        vs = [min(1.0, v * gain) for v in vs]

    out = []
    for (h, s, _), v in zip(hsv, vs):
        r, g, b = colorsys.hsv_to_rgb(h, s, min(1.0, max(v, v_floor)))
        out.append((round(r * 255), round(g * 255), round(b * 255)))
    return out


def _column_means(img, width):
    """把封面横向切成 width 条细列，返回每列的「加权平均 RGB」（浮点三元组）。

    权重 = (0.25 + 0.75*s) × (0.35 + 0.65*v)：大面积暗背景 / 纯黑不会把该列
    平摊成灰，彩色主体仍能主导；同时又不像「量化取主色」那样离散 ——
    细列之间本来就连续，这是后面能做平滑过渡的前提。
    """
    img = img.resize((width, COVER_SAMPLE_HEIGHT), Image.BILINEAR)
    pixels = list(img.getdata())
    acc = [[0.0, 0.0, 0.0, 0.0] for _ in range(width)]
    for y in range(COVER_SAMPLE_HEIGHT):
        row = y * width
        for x in range(width):
            r, g, b = pixels[row + x]
            mx, mn = max(r, g, b), min(r, g, b)
            s = 0.0 if mx == 0 else (mx - mn) / mx
            v = mx / 255.0
            w = (0.25 + 0.75 * s) * (0.35 + 0.65 * v)
            a = acc[x]
            a[0] += r * w
            a[1] += g * w
            a[2] += b * w
            a[3] += w
    out = []
    for a in acc:
        if a[3] > 0:
            out.append((a[0] / a[3], a[1] / a[3], a[2] / a[3]))
        else:
            out.append((0.0, 0.0, 0.0))
    return out


def _smooth_series(series, radius):
    """三角核（Bartlett）加权滑动平均：中心权重最大，向两边线性递减。

    端点只用存在的那一侧并按实际权重和归一化，首尾不会凭空变暗。
    输入 / 输出都是 (r,g,b) 三元组；输出为浮点，调用方自行取整。
    """
    m = len(series)
    r = max(0, int(radius))
    if r <= 0 or m == 0:
        return [tuple(float(v) for v in c) for c in series]
    out = []
    for i in range(m):
        ar = ag = ab = wsum = 0.0
        for j in range(max(0, i - r), min(m - 1, i + r) + 1):
            w = r + 1 - abs(j - i)
            c = series[j]
            ar += c[0] * w
            ag += c[1] * w
            ab += c[2] * w
            wsum += w
        out.append((ar / wsum, ag / wsum, ab / wsum))
    return out


def cover_columns(img_bytes, n=LED_COUNT):
    """封面 -> n 组**连续渐变**色（灯带从左到右 = 封面从左到右）。

    步骤：细列加权平均（n×COVER_OVERSAMPLE 条）-> 三角核平滑
    -> 组内再平均降采样 -> 明度归一化。相邻组共享大半像素，颜色不会硬跳，
    形成平滑过渡；同时仍保留封面的左右空间信息，不是糊成一个平均色。
    """
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    fine = n * COVER_OVERSAMPLE
    means = _column_means(img, fine)
    smoothed = _smooth_series(
        means, int(round(COVER_SMOOTH_GROUPS * COVER_OVERSAMPLE)))
    cols = []
    for g in range(n):
        chunk = smoothed[g * COVER_OVERSAMPLE:(g + 1) * COVER_OVERSAMPLE]
        cols.append(tuple(round(sum(c[k] for c in chunk) / len(chunk))
                          for k in range(3)))
    cols = _normalize_values(cols)
    # 明度归一化是逐色的非线性映射（gamma + v_floor），会在很暗的位置留下折点；
    # 最后轻抹一遍，让 60 颗之间的变化率也连续，而不是只有数值连续。
    return [tuple(round(v) for v in c)
            for c in _smooth_series(cols, COVER_FINAL_SMOOTH)]


class MediaWatcher:
    """
    轮询 SMTC。注意：read_async 必须 await，否则第二次调用拿到空 buffer。
    没装 WinRT 绑定 / Pillow 时 available=False，灯保持熄灭。
    """

    STATUS_NAME = {0: "Closed", 1: "Opened", 2: "Changing", 3: "Stopped",
                   4: "Playing", 5: "Paused"}

    def __init__(self, app_filter: str = None):
        self.available = HAS_MEDIA
        self.app_filter = app_filter          # 例如只认网易云：填它的 AppUserModelID
        self.playing = False
        self.title = ""
        self.artist = ""
        self.app_id = ""
        self.status = ""
        self.position = 0.0                   # 已播放秒数（播放器可能不上报）
        self.duration = 0.0                   # 总时长秒数，0 表示未知
        self.elapsed = 0.0                    # 兜底：从认出这首曲子起算的秒数
        self._last_title = None
        self._title_since = time.monotonic()

        # 切歌时标题和封面【不是同时更新】的：先用"标题变了才解码"做缓存，
        # 结果第一次读到的还是上一首的封面，标题却已经是新的，颜色就永远锁死在旧封面。
        # 改成比对封面字节哈希，切歌后持续重试直到拿到真正的新封面。
        self.columns = []                     # 封面从左到右的 60 颗连续渐变色
        self._pending = False
        self._pending_since = 0.0
        self._thumb_hash = None
        self.color = None                     # 主色（palette[0]）
        self.palette = []                     # [(rgb, weight), ...] 九宫格配色
        self.cover_updates = 0                # 每次成功解码新封面 +1，给板载 LED 报「就绪」
        self._err_logged = False

        # 事件驱动：切歌时 SMTC 会回调，立刻置 dirty 让轮询循环马上采样
        # 轮询兜底间隔 0.5s（原来是 3s，所以切歌要等 1~3 秒才变）
        self._dirty = False
        self._session = None
        self._registered = None
        self._tok_props = None
        self._tok_play = None
        if not self.available:
            missing = []
            if MEDIA_BACKEND is None:
                missing.append("WinRT 绑定")
            if not HAS_PILLOW:
                missing.append("Pillow")
            print(f"  [媒体] 缺少 {' 和 '.join(missing)}，媒体态已禁用。安装：")
            print("           pip install winrt-runtime winrt-Windows.Media.Control"
                  " winrt-Windows.Storage.Streams Pillow")

    # ---- 采集 ----
    async def _read_thumbnail(self, thumb_ref) -> bytes:
        """
        read_async 必须 await，否则第二次调用拿到空 buffer。
        新版 PyWinRT 里 Buffer 直接支持 bytes()；旧版要用 DataReader 填充数组。
        （DataReader.read_bytes(n) 这种写法在新版会报 "a bytes-like object is required, not 'int'"）
        """
        buffer = Buffer(5 * 1024 * 1024)
        readable = await thumb_ref.open_read_async()
        await readable.read_async(buffer, buffer.capacity, InputStreamOptions.READ_AHEAD)
        try:
            return bytes(buffer)
        except TypeError:
            reader = DataReader.from_buffer(buffer)
            out = bytearray(buffer.length)
            reader.read_bytes(out)
            return bytes(out)

    async def _poll_async(self):
        """
        不用 get_current_session()：那只返回系统认定的当前会话，
        网易云没被选中时就永远拿不到。改为遍历全部会话。
        """
        mgr = await _MediaManager.request_async()
        all_sessions = list(mgr.get_sessions())
        if not all_sessions:
            return None

        if self.app_filter:
            target = None
            for s in all_sessions:
                if self.app_filter in (s.source_app_user_model_id or ""):
                    target = s
                    break
            if target is None:
                return None
        else:
            # 优先挑真正在播的；都不在播就退回系统当前会话，再退回第一个
            target = None
            for s in all_sessions:
                try:
                    if int(s.get_playback_info().playback_status) == 4:
                        target = s
                        break
                except Exception:
                    continue
            if target is None:
                target = mgr.get_current_session() or all_sessions[0]

        self._session = target
        app_id = target.source_app_user_model_id or ""
        props = await target.try_get_media_properties_async()
        status = int(target.get_playback_info().playback_status)

        # 时间轴 -> 秒。字段是 datetime.timedelta。
        # 注意网易云这类桌面端常常不上报（全 0），显示层要能自适应隐藏进度条。
        pos = dur = 0.0
        try:
            tl = target.get_timeline_properties()
            if tl is not None:
                if tl.position is not None:
                    pos = max(0.0, tl.position.total_seconds())
                if tl.end_time is not None:
                    dur = max(0.0, tl.end_time.total_seconds())
        except Exception:
            pass

        return {
            "app_id": app_id,
            "title": props.title or "",
            "artist": props.artist or "",
            "status": self.STATUS_NAME.get(status, str(status)),
            "playing": status == 4,                 # 4 = Playing
            "thumb": props.thumbnail,
            "position": pos,
            "duration": dur,
        }

    def _log_err(self, msg):
        """异常只提示一次，避免后台线程每 3 秒刷屏，但也不能静默吞掉"""
        if not self._err_logged:
            print(f"  [媒体] {msg}（只提示一次）")
            self._err_logged = True

    def _apply(self, info):
        """更新标量字段。返回 True 表示正在播放且带封面，需要（可能）解码"""
        if info is None:
            self.playing = False
            self.title = self.artist = self.app_id = self.status = ""
            self.position = self.duration = 0.0
            return False
        self.app_id = info["app_id"]
        self.title = info["title"]
        self.artist = info["artist"]
        self.status = info["status"]
        self.playing = info["playing"]
        self.position = info.get("position", 0.0)
        self.duration = info.get("duration", 0.0)

        # 播放器不报时间轴时，用"认出这首曲子"的时刻兜底，至少时间会走
        if self.title != self._last_title:
            self._last_title = self.title
            self._title_since = time.monotonic()
            self._pending = True                      # 换歌了，等新封面
            self._pending_since = time.monotonic()
        self.elapsed = time.monotonic() - self._title_since
        return self.playing and info["thumb"] is not None

    async def _maybe_decode(self, thumb, timeout=5.0):
        """切歌后反复取封面，直到字节哈希变化为止（说明新封面真的到了）"""
        if not self._pending:
            return
        if time.monotonic() - self._pending_since > timeout:
            self._pending = False                     # 超时（比如新歌没封面）
            return
        try:
            data = await self._read_thumbnail(thumb)
        except Exception as e:
            self._log_err(f"封面读取失败: {type(e).__name__}: {e}")
            return
        if not data:
            return
        digest = hashlib.md5(data).hexdigest()
        if digest == self._thumb_hash:
            return                                    # 还是旧封面，下轮再试
        self._thumb_hash = digest
        self._set_palette(data)
        self.cover_updates += 1               # 「封面真正换好」的瞬间，板载 LED 会报一声
        self._pending = False

    def _set_palette(self, data):
        self.palette = analyze_cover(data)
        self.columns = cover_columns(data, LED_COUNT)   # 60 颗，别沿用原来的 8 列
        self.color = self.palette[0][0] if self.palette else None

    # ---- 事件驱动：切歌即时响应 ----
    def _on_changed(self, sender, args):
        self._dirty = True

    async def _ensure_events(self):
        """会话换了就重新注册回调（换播放器时旧回调就失效了）"""
        s = self._session
        if s is None or s is self._registered:
            return
        if self._registered is not None:
            for rm, tok in (("remove_media_properties_changed", self._tok_props),
                            ("remove_playback_info_changed", self._tok_play)):
                try:
                    if tok is not None:
                        getattr(self._registered, rm)(tok)
                except Exception:
                    pass
            self._tok_props = self._tok_play = None
        try:
            self._tok_props = s.add_media_properties_changed(self._on_changed)
            self._tok_play = s.add_playback_info_changed(self._on_changed)
            self._registered = s
        except Exception as e:
            self._log_err(f"事件注册失败（退化为纯轮询）: {type(e).__name__}: {e}")

    async def _async_loop(self, stop_event, poll_interval=0.5, check_interval=0.08):
        last = 0.0
        while not stop_event.is_set():
            if self._dirty or (time.monotonic() - last) >= poll_interval:
                try:
                    info = await self._poll_async()
                    if self._apply(info):
                        await self._maybe_decode(info["thumb"])
                except Exception as e:
                    self._log_err(f"采集异常: {type(e).__name__}: {e}")
                await self._ensure_events()
                self._dirty = False
                last = time.monotonic()
            await asyncio.sleep(check_interval)

    def run_forever(self, stop_event):
        """
        在后台线程里跑常驻事件循环。
        用常驻循环而不是反复 asyncio.run()，事件回调才有机会被派发。
        """
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_loop(stop_event))
        finally:
            try:
                loop.close()
            except Exception:
                pass


# ============================================================
# 麦克风占用检测（Windows 隐私同意记录，零第三方依赖）
# ============================================================
# Windows 10 1903+ 会为每个「真的打开过麦克风捕获流」的进程记录开始/结束时间，
# 放在 HKCU\...\CapabilityAccessManager\ConsentStore\microphone 下：
#     ...\microphone\<打包应用包名>\LastUsedTimeStart / LastUsedTimeStop
#     ...\microphone\NonPackaged\<Win32 路径，反斜杠写成 #>\...
# 两个值都是 FILETIME（1601-01-01 起算的 100ns 计数，REG_QWORD）。
# Start > Stop 就是「这个进程正在录音」。任务栏那个「麦克风正在使用」小图标
# 用的也是这份数据，所以灯的含义跟系统的说法完全一致。
#
# 实测（本机用 ffmpeg 开 dshow 捕获）：启动 0.65s 内检出，全程稳定，退出 0.7s 内归零。
# 不用 WASAPI 枚举捕获会话：那要 pycaw / comtypes 或一大堆 COM ctypes，
# 而灯效根本不需要毫秒级精度 —— 注册表方案零依赖、够准、也不用管设备枚举。
#
# 两个必须处理的坑：
#   1. 输入法 / 语音助手会短暂开一下麦克风（本机记录里最短只有 75ms），
#      不过滤灯就会莫名其妙闪橙。所以下面有 ON / OFF 双向去抖。
#      ON 只留 0.2s：仍大于 75ms 的短脉冲，但人一开口就能马上看到灯。
#   2. 进程崩溃或被强杀时 Stop 不会写入，Start > Stop 会永远成立（僵尸记录）。
#      所以超过 MIC_STALE_HOURS 的 Start 一律忽略。

MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
MIC_POLL_INTERVAL = 0.05     # 注册表扫描间隔（秒）；20Hz，单次 <1ms，主循环里顺手扫
MIC_ON_DELAY = 0.2           # 连续在用 0.2s 就认；配合 0.05s 轮询，最坏约 0.25s 出灯
MIC_OFF_DELAY = 1.5          # 关去抖保持原样：说话中的停顿不该让灯来回跳
MIC_STALE_HOURS = 6.0        # 更早的 Start 视为僵尸记录

# ---- 电平表（VU）参数 ----
# 颜色：按「亮起顺序」从绿(120°) 线性走到红(0°)，中途自然经过黄(60°)、橙(30°)。
# 方向：WS2812 帧里 index 0 是数据线进来的第一颗（离板子最近），index 7 是末端（最远）。
#       默认从最近端往最远端点亮，即 index 0 -> 7；--mic-reverse 翻回远 -> 近。
MIC_HUE_FIRST = 120.0        # 第一颗：绿
MIC_HUE_LAST = 0.0           # 第八颗：红
MIC_SAT = 0.95
MIC_VALUE = 1.0
MIC_ORDER = list(range(LED_COUNT))                        # [0,1,...,59] 近 -> 远（默认）
MIC_ORDER_REVERSED = list(range(LED_COUNT - 1, -1, -1))   # [59,...,0] 远 -> 近

# ---- 音量 -> 亮灯颗数 / 亮度 ----
# 60 颗下这两条曲线必须配套，否则会「颗数先铺开、亮度后起来」：
# 旧版线性颗数 1+lv×59 在 lv=0.10 已经 6 颗，而亮度前 10% 几乎水平（恒 2/255），
# 于是极低声一片全黑，到 lv≈0.13 亮度刚越过可见阈值时 8 颗一起显形。
# 现在颗数按 t^1.5 长（低段慢）、亮度从门限起就连续爬升，
# **每颗亮起时立刻看得见**，于是一颗一颗长出来而不是突然冒一片。
# 亮度必须按最终占空比直出，不能过 gamma：gamma(0.1)≈0.4/255，10% 会肉眼全黑。
# 起点不能是 0：0.2% × 255 经 int 截断就是 0/255，门限刚过那颗会「逻辑点亮、
# 物理全黑」。给 0.9% 的极低起点，并随 lv 连续上升（不是固定平台）。
MIC_SOUND_GATE = 0.02        # 低于此 = 没声音/极低声：**一颗都不亮**
VU_COUNT_EXP = 1.5           # 颗数曲线指数：1.0=线性（旧），>1 低段更缓、高段更陡
MIC_BRIGHT_STOPS = (         # (电平, 最终 PWM 占空比)，分段线性、单调递增
    (0.00, 0.009),           # 门限以下不取值（mic_brightness 直接返回 0）
    (0.02, 0.012),           # 底噪 1 颗：1.2% ≈ 3/255 微光
    (0.10, 0.05),            # 5% ≈ 13/255，此时才 2.4 颗，不会突然一片
    (0.30, 0.20),
    (1.00, 0.80),            # 最大声仍 80%
)

# ---- 电平归一化：固定量程（别再用「历史最大峰值」当满档） ----
# 旧版有个真 bug：peak 一超过参考值就立刻把参考抬到 peak，于是
# target=(peak-floor)/(ref-floor)=1.0 —— 任何正常说话都会直接算成满档 8 颗。
# 现在量程固定不动：peak 从噪声门限线性映射到 MIC_FULL_PEAK，声音大就是大、
# 声音小就是小，不会「自己把量程撑大」。
# 麦克风增益因机器而异，用 --mic-calibrate 实测峰值、--mic-full-peak 校准。
MIC_NOISE_FLOOR = 0.006      # 实测安静底噪 0.0066~0.0105，低于此不算有声
# 默认吃满 WASAPI peak 的整个 0~1 物理范围：贴嘴说话不再一下打满。
# 旧默认 0.35 只用了 1/3 量程，再叠加「lv>=0.70 就 8 颗」，实际 peak≈0.25 就到顶。
MIC_FULL_PEAK = 1.00         # 满档对应的设备峰值（默认，可用 --mic-full-peak 改）
# 60 颗 = 60 级分辨率（每颗约 1/59 lv）。8 颗时代的两级 35ms 低通串联会把
# 短促鼓点削平：实测 lv=0.9 只持续 1~3 帧时，理想 54 颗只打到 31~47 颗。
# 现在电平低通统一走下面的快起慢落（10ms/90ms，放歌与麦克风共用），
# 颜色平滑压到 12ms（50Hz 下一帧跟上 81%），瞬时峰值才打得到对应档位。
# 嫌闪就把 MIC_SMOOTH_TAU 调回 0.035，或把慢落调得更大。
MIC_LEVEL_TAU = 0.012        # MicLevel 类默认双向值（仅兜底；实际两实例都显式传 10/90ms）
MIC_SMOOTH_TAU = 0.012       # 声音驱动灯效的颜色平滑（放歌 + 麦克风共用）

# ---- 放歌时：系统输出峰值驱动封面配色灯 ----
# 读默认输出设备的 IAudioMeterInformation（同一套 COM 代码，只是端点从
# eCapture 换成 eRender），不开捕获流、不碰 ConsentStore、戴耳机也照样有值。
RENDER_NOISE_FLOOR = 0.0     # 数字输出没有底噪，静音就是 0
RENDER_FULL_PEAK = 1.00      # 满档对应的输出峰值（--render-full-peak 可调）
# 放歌是「PWM 域」亮度系数：封面色必须**先逐通道过 gamma** 再乘它，
# 否则等于把感知颜色直接当 PWM 发出去，亮通道拉满、暗通道也被抬起 → 泛白过曝。
# 上限 = 1.0：host 发满 255，由固件 BRIGHTNESS_CAP=128 统一限流，**host 不再
# 二次打折**。旧的 0.37 会让白色封面只发 94/255、固件后仅剩 47/255（18.5%）。
# 亮度从 RENDER_BRIGHT_FLOOR=0.01 爬升到 1.0：1% 是**曲线的起点**，
# 不是「低音量段固定不变」的保底平台 —— 后者才会被看成「声音很小灯却很亮」。
# 旧版是线性 lv，低段太暗：lv<0.06 全在 2~7/255，等亮度可见时颗数已铺开 5 颗。
# 现在用 lv^0.7 把前端抬起来，满档直接吃满固件上限。
# 数字输出没有底噪、不套麦克风门限。
RENDER_BRIGHT_MAX = 1.0
RENDER_BRIGHT_FLOOR = 0.01
RENDER_BRIGHT_GAMMA = 0.7    # 亮度曲线指数：1.0=线性（旧），<1 前端抬得更快
# 亮度系数单独做慢平滑（与「亮几颗」的快起慢落解耦）。
# 低电平时暗封面灯珠的 raw 被 int 截断成 (0,0,0)，全靠 with_glow 的整数
# floor 发光；floor 若跟着瞬态峰值每帧在 1/2/3/4 之间跳，1↔2 就是亮度翻倍，
# 补底颜色按感知域比例取整也跟着跳 —— 前 12 颗看起来又闪又跳色。
# 实测 tau=120ms 可把 120 帧里的 floor 跳变从 119 次压到 5 次（稳态恒定）。
# 只影响亮度，颗数仍用原始 lv，快起慢落和 60 级精度一点不动。
RENDER_BRIGHT_TAU = 0.12
# 真静音（数字输出精确为 0，没有底噪）时一颗都不亮；刚过门限的极小声仍从 1% 起步。
# 只用来区分「完全没声音」和「有一点声音」，别调大，否则会吞掉小音量段。
RENDER_SILENCE_GATE = 0.005
# 声音电平低通：标准 VU 的「快起慢落」（attack:release = 1:9）。
# **放歌与麦克风 VU 共用这一对参数**（Monitor 里两个 MicLevel 都传它），
# 只改一个旋钮两边手感就一致。参数名沿用历史 --render-attack/--render-release，
# 别被 "render" 误导：它也管麦克风。
# 50Hz 帧间隔 20ms：attack 10ms（k=0.865，一帧基本到位）让瞬态打得到高档；
# release 90ms 把鼓点/语句之间的谷值托住，整条更稳、不会猛地掉下去。
# 只影响**下降方向**：上升仍由 attack 决定，实测短促峰值在 release 25/90ms
# 下逐帧完全相同（48.5 / 53.3 / 54.0 / 54.1 颗），快起一点没被牵连。
# 代价是拖尾：峰值后落到 lv<=0.3 从 60ms 变 180ms，方波谷值 0.1 -> 0.187。
# ⚠️ --autostart install 会把这两个参数写死在任务命令行里，改默认值对已装
#    任务无效：要吃到新值需重跑 install 或在任务计划里改参数。
#    颜色平滑（12ms）、颗数/亮度曲线不读这两个参数。
RENDER_LEVEL_ATTACK_TAU = 0.010
RENDER_LEVEL_RELEASE_TAU = 0.090
# 暗封面色过 gamma 后往往只剩 4~19/255，再乘约 0.35 的亮度系数就只有 3~5/255：
# 逻辑上点亮了、肉眼却看不见（表现为「前两颗不亮，从第三颗才亮」）。
# with_glow() 按自身色相比例把最终 PWM 补到这个「最低可见亮度」。
# 强度必须**跟着亮度走**（floor = 本值 × bright / RENDER_BRIGHT_MAX）：固定值会让
# 深色封面从 lv=0 到 1.0 全程锁在同一个输出，又变回「固定平台」；
# 现在静音侧 floor≈1（保留 1% 起步）、满档 18，全程随音量连续变化。
# 实测：暗封面 (92,88,80) 过 gamma 是 (15,13,10)，×0.35 只有 (5,4,3) → 补到 18/255 才可见。
RENDER_MIN_GLOW = 18
# 保底放大时按「感知域」比例，并轻度去饱和（0 = 原色相，1 = 全灰）。
# gamma 是 2.8 次方，拿 PWM 域的通道比例当色相会把近中性的暗蓝灰 (56,59,75)
# 放大成纯蓝 (4,4,8)；按感知比例 + 25% 去饱和才是 (6,7,8) 这种偏米白的浅蓝。
# 真蓝 (20,30,60) 补完仍是 (4,5,8)，色相不会被抹掉。
GLOW_DESAT = 0.25

# ---- 60 级严格档位 ----
# 8 颗时代怕「最后一颗太早亮」，加了 frac>0.06 迟滞和 RENDER_LAST_LED_LV
# 把末颗单独延后。60 颗下这两条只会吞精度：每颗约 1.7% lv，6% 的迟滞
# 相当于好几颗的当量，最后一颗更是几乎不出现。
# 现在统一走 vu_steps()：n 的小数部分一律点亮下一颗渐入，lv=1.0 恰好 60 颗全亮。

# WASAPI 设备峰值表接口。IID 后四位是 D008E73E0064 —— 网上常见的
# D01E1FE83D21C 是错的，Activate 会直接回 0x80004002 E_NOINTERFACE。
IID_IAUDIO_METER = "C02216F6-8C67-4B5B-9D00-D008E73E0064"
CLSID_MM_DEVICE_ENUM = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_IMM_DEVICE_ENUM = "A95664D2-9614-4F35-A746-DE8DB63617E6"

# 1601-01-01 -> 1970-01-01 的秒数，用来把 time.time() 换算成 FILETIME
_FILETIME_EPOCH_DELTA = 11644473600


def _filetime(t):
    return int((t + _FILETIME_EPOCH_DELTA) * 10_000_000)


def _short_app_name(name):
    """NonPackaged 的键名是完整路径（反斜杠写成 #），取最后一段给面板显示"""
    return (name.replace("#", "\\").split("\\")[-1] or name)


def mic_sessions_in_use(records, now_ft):
    """records: [(键名, start, stop)] -> 正在使用麦克风的应用名列表。

    纯函数，方便离线验证三条判据：Start>Stop、僵尸超时、名字截断。
    """
    stale = int(MIC_STALE_HOURS * 3600 * 10_000_000)
    out = []
    for name, start, stop in records:
        if start <= 0 or start <= stop:
            continue                       # Stop 已写回 = 结束了
        if now_ft - start > stale:
            continue                       # 崩溃残留，别永远亮橙
        out.append(_short_app_name(name))
    return out


class MicLevelMeter:
    """WASAPI IAudioMeterInformation：只读设备级峰值，不打开任何捕获流。

    data_flow / role 决定读哪个默认端点：
      (1, 1) = eCapture / eMultimedia -> 麦克风输入峰值（原有 VU 用这个）
      (0, 0) = eRender  / eConsole    -> 系统播放混音峰值（放歌时驱动灯效用这个）
    输出端点这条路连捕获流都不用开，纯读 meter，更不会污染 ConsentStore。

    不开捕获流是关键 —— 自己起录音会把进程写进 ConsentStore，
    于是「麦克风没在使用」永远不成立。峰值表不产生流，判定保持干净。
    纯 ctypes，零第三方依赖；本机实测单次调用约 41 微秒。
    """

    def __init__(self, data_flow=1, role=1):
        self.data_flow = data_flow
        self.role = role
        self.available = False
        self.peak = 0.0
        self.error = ""
        self._meter = 0
        self._get_peak = None
        self._cfloat = None
        self._byref = None
        if os.name != "nt":
            self.error = "非 Windows"
            return
        try:
            import ctypes
            from ctypes import wintypes, POINTER, byref, c_void_p, c_float, c_int

            class _GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
                def __init__(self, text):
                    super().__init__()
                    h = text.replace("{", "").replace("}", "").replace("-", "")
                    self.Data1 = int(h[0:8], 16)
                    self.Data2 = int(h[8:12], 16)
                    self.Data3 = int(h[12:16], 16)
                    for i in range(8):
                        self.Data4[i] = int(h[16 + i * 2:18 + i * 2], 16)

            def vtcall(ptr, idx, argtypes):
                vt = ctypes.cast(ptr, POINTER(POINTER(c_void_p))).contents
                return ctypes.WINFUNCTYPE(c_int, *argtypes)(vt[idx])

            ole32 = ctypes.windll.ole32
            ole32.CoInitialize.argtypes = [c_void_p]
            ole32.CoInitialize.restype = c_int
            ole32.CoCreateInstance.argtypes = [
                POINTER(_GUID), c_void_p, wintypes.DWORD,
                POINTER(_GUID), POINTER(c_void_p)]
            ole32.CoCreateInstance.restype = c_int

            # 本线程可能已被 WinRT 初始化成 MTA：S_FALSE(1) 与
            # RPC_E_CHANGED_MODE(0x80010106) 都表示「COM 已可用」，继续用即可。
            # 刻意不调 CoUninitialize —— 别把别人初始化的 COM 卸掉。
            hr = ole32.CoInitialize(None) & 0xffffffff
            if hr not in (0, 1, 0x80010106):
                raise OSError("CoInitialize 0x%08X" % hr)

            p_enum = c_void_p()
            hr = ole32.CoCreateInstance(
                byref(_GUID(CLSID_MM_DEVICE_ENUM)), None, 23,
                byref(_GUID(IID_IMM_DEVICE_ENUM)), byref(p_enum)) & 0xffffffff
            if hr or not p_enum.value:
                raise OSError("CoCreateInstance 0x%08X" % hr)

            # IMMDeviceEnumerator::GetDefaultAudioEndpoint = vtable[4]
            # (1,1)=默认麦克风输入；(0,0)=默认输出设备（系统播放混音峰值）
            p_dev = c_void_p()
            hr = vtcall(p_enum, 4,
                        [c_void_p, c_int, c_int, POINTER(c_void_p)])(
                            p_enum.value, self.data_flow, self.role,
                            byref(p_dev)) & 0xffffffff
            if hr or not p_dev.value:
                raise OSError("GetDefaultAudioEndpoint 0x%08X" % hr)

            # IMMDevice::Activate = vtable[3]
            p_meter = c_void_p()
            hr = vtcall(p_dev, 3,
                        [c_void_p, POINTER(_GUID), wintypes.DWORD,
                         c_void_p, POINTER(c_void_p)])(
                            p_dev.value, byref(_GUID(IID_IAUDIO_METER)), 23,
                            None, byref(p_meter)) & 0xffffffff
            if hr or not p_meter.value:
                raise OSError("Activate(IAudioMeterInformation) 0x%08X" % hr)

            # IAudioMeterInformation::GetPeakValue = vtable[3]
            self._meter = p_meter.value
            self._get_peak = vtcall(
                p_meter, 3, [c_void_p, POINTER(c_float)])
            self._cfloat = c_float
            self._byref = byref
            self.available = True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            print(f"  [麦克风] 电平接口不可用，退化为二值指示：{self.error}")

    def read(self):
        """返回 0~1 的峰值。读失败保留上次值，不让灯带闪一下。"""
        if not self.available:
            return 0.0
        v = self._cfloat()
        hr = self._get_peak(self._meter, self._byref(v))
        if hr:
            return self.peak
        self.peak = max(0.0, min(1.0, float(v.value)))
        return self.peak


class MicLevel:
    """把原始 peak 按固定量程归一化成 0~1 电平（+ 快平滑）。纯逻辑，可离线测。

    ⚠️ 不要再改成「滚动峰值参考」：只要让满档跟着历史最大声音跑，
    正常说话就会立刻变成 target=1.0（8 颗全亮），这正是之前那个 bug。
    """

    def __init__(self, full_peak=MIC_FULL_PEAK, noise_floor=MIC_NOISE_FLOOR,
                 attack_tau=MIC_LEVEL_TAU, release_tau=MIC_LEVEL_TAU):
        self.value = 0.0        # 平滑后的电平，灯效读这个
        self.peak = 0.0         # 本次原始峰值，面板显示
        self.noise_floor = float(noise_floor)
        self.full = max(self.noise_floor + 1e-3, float(full_peak))   # 满档峰值
        # 默认值只是「没显式传参」时的双向兜底；实际两个实例（放歌 / 麦克风）
        # 都由 Monitor 显式传同一对 10ms/90ms 的快起慢落参数。
        self.attack_tau = max(1e-4, float(attack_tau))
        self.release_tau = max(1e-4, float(release_tau))
        self._last = None

    def update(self, peak, now=None, dt=None):
        now = time.time() if now is None else now
        if dt is None:
            dt = FRAME_INTERVAL if self._last is None else (now - self._last)
        dt = max(0.0, min(0.5, dt))
        self._last = now
        self.peak = peak
        span = max(1e-6, self.full - self.noise_floor)
        target = min(1.0, max(0.0, peak - self.noise_floor) / span)
        # 非对称：上升用 attack、下降用 release（两者相等时就是原来的双向低通）
        tau = self.attack_tau if target > self.value else self.release_tau
        k = 1.0 - math.exp(-dt / tau)
        self.value += (target - self.value) * k
        # 吸附：一阶低通永远差一点点，不处理的话最大声会停在「7 颗 + 第 8 颗 99.9% 亮」
        if abs(target - self.value) < 1e-3:
            self.value = target
        return self.value


class MicWatcher:
    """同步轮询注册表，不额外开线程 —— 扫几十个子键不到 1ms，主循环里顺手就调了"""

    def __init__(self):
        self.available = (os.name == "nt")
        self.in_use = False       # 去抖后的稳定判定，灯效读这个
        self.raw = False          # 这一轮扫描的原始结果
        self.apps = []            # 正在用的应用名（面板显示）
        self._last_poll = 0.0
        self._on_since = None
        self._off_since = None
        self._err_logged = False
        self._reg = None
        if self.available:
            try:
                import winreg
                self._reg = winreg
            except ImportError:
                self.available = False
                print("  [麦克风] winreg 不可用，麦克风指示已禁用")

    def _scan(self):
        """返回 [(键名, start, stop)]。没有时间戳的子键（从没用过麦克风）跳过"""
        reg = self._reg
        out = []
        for suffix in ("", "\\NonPackaged"):
            try:
                root = reg.OpenKey(reg.HKEY_CURRENT_USER, MIC_KEY + suffix)
            except OSError:
                continue
            try:
                count = reg.QueryInfoKey(root)[0]
                for i in range(count):
                    try:
                        name = reg.EnumKey(root, i)
                        sub = reg.OpenKey(root, name)
                    except OSError:
                        continue
                    try:
                        start = int(reg.QueryValueEx(sub, "LastUsedTimeStart")[0])
                    except (OSError, ValueError, TypeError):
                        reg.CloseKey(sub)
                        continue
                    try:
                        # Stop 缺失 = 第一次开麦克风、还没结束，按 0 处理才算「在用」
                        stop = int(reg.QueryValueEx(sub, "LastUsedTimeStop")[0])
                    except (OSError, ValueError, TypeError):
                        stop = 0
                    reg.CloseKey(sub)
                    out.append((name, start, stop))
            finally:
                reg.CloseKey(root)
        return out

    def poll(self, now=None):
        """节流扫描 + 双向去抖，返回稳定的 in_use"""
        now = time.time() if now is None else now
        if not self.available or (now - self._last_poll) < MIC_POLL_INTERVAL:
            return self.in_use
        self._last_poll = now
        try:
            records = self._scan()
        except Exception as e:
            if not self._err_logged:
                self._err_logged = True
                print(f"  [麦克风] 读注册表失败，麦克风指示已禁用：{e}")
            self.available = False
            return False

        self.apps = mic_sessions_in_use(records, _filetime(now))
        self.raw = bool(self.apps)
        if self.raw:
            self._off_since = None
            if self._on_since is None:
                self._on_since = now
            if not self.in_use and (now - self._on_since) >= MIC_ON_DELAY:
                self.in_use = True
        else:
            self._on_since = None
            if self._off_since is None:
                self._off_since = now
            if self.in_use and (now - self._off_since) >= MIC_OFF_DELAY:
                self.in_use = False
        return self.in_use


def mic_order(reverse=False):
    """点亮顺序：默认 [0..7]（离板子最近 -> 最远）；--mic-reverse 翻回 [7..0]"""
    return MIC_ORDER_REVERSED if reverse else MIC_ORDER


def mic_hue(i):
    """第 i 颗（按亮起顺序）的色相：120° 绿 -> 0° 红，**逐颗连续插值**。

    60 颗就是 60 段：绿 -> 黄(60°) -> 橙(30°) -> 红，相邻两颗色相差 2°，
    不是「前若干颗绿、再若干颗黄」那种四五段硬分段。
    """
    t = i / max(1, LED_COUNT - 1)
    return MIC_HUE_FIRST + (MIC_HUE_LAST - MIC_HUE_FIRST) * t


def mic_led_count(level):
    """电平 -> 亮起颗数（0 或 1.0~LED_COUNT，含小数）。

    低于 MIC_SOUND_GATE 直接 0 颗（真静音全灭）；从门限起按 t^VU_COUNT_EXP 长到
    lv=1.0 的 LED_COUNT 颗 —— 门限刚过（底噪级别）恰好 **1 颗**，最大声 **60 颗**。
    低段刻意压慢：旧线性曲线在 lv=0.10 就铺开 6 颗，而那时亮度仍只有 2/255，
    等亮度越过可见阈值时 8 颗一起显形，看着就像「突然亮一片」。
    """
    lv = max(0.0, min(1.0, level))
    if lv < MIC_SOUND_GATE:
        return 0.0
    t = (lv - MIC_SOUND_GATE) / max(1e-6, 1.0 - MIC_SOUND_GATE)
    return 1.0 + t ** VU_COUNT_EXP * (LED_COUNT - 1)


def render_led_count(level):
    """放歌：电平 -> 亮起颗数（1~LED_COUNT），与麦克风共用同一条幂曲线。

    单独一个函数是为了让 compute_target() 和终端面板显示同一个数字 ——
    低段压慢之后，两处各自写 1+lv×59 会立刻不同步，很难查。
    """
    lv = max(0.0, min(1.0, level))
    return 1.0 + lv ** VU_COUNT_EXP * (LED_COUNT - 1)


def vu_steps(n):
    """把「亮几颗（可含小数）」拆成 (满亮颗数, 是否多长一颗, 渐入系数)。

    60 颗要严格逐级：只要 n 有小数就点亮下一颗渐入，**不设 frac>0.06 迟滞**，
    也不给最后一颗单独延后 —— 那两条都是 8 颗时代怕「到顶太早」的补丁，
    在 60 级分辨率上只会吞精度、让第 60 颗几乎不出现。
    n=1 -> 1 颗；n=30.5 -> 30 颗满 + 1 颗半亮；n=60 -> 恰好 60 颗全亮。
    放歌与麦克风 VU 共用，面板显示的小数就是最后一颗的渐入比例。
    """
    n = max(0.0, min(float(LED_COUNT), n))
    whole = int(n)
    frac = n - whole
    extra = 1 if (whole < LED_COUNT and frac > 1e-6) else 0
    return whole, extra, frac


def mic_brightness(level):
    """电平 -> 最终 PWM 占空比（0~1）。按 MIC_BRIGHT_STOPS 分段线性插值。

    注意这是「占空比」不是「感知亮度」：底噪级别 1.2%（3/255）到 lv=1.0 的
    80% 是灯珠实际发出来的比例，必须绕过 gamma，否则低段全被压成 0。
    前 10% 电平要连续爬升（1.2% -> 5%），不能再是旧版那条几乎水平的平段。
    门限以下直接 0。
    """
    lv = max(0.0, min(1.0, level))
    if lv < MIC_SOUND_GATE:
        return 0.0
    for (x0, y0), (x1, y1) in zip(MIC_BRIGHT_STOPS, MIC_BRIGHT_STOPS[1:]):
        if lv <= x1:
            t = max(0.0, min(1.0, (lv - x0) / max(1e-6, x1 - x0)))
            return y0 + (y1 - y0) * t
    return MIC_BRIGHT_STOPS[-1][1]


def render_brightness(level):
    """放歌用的 PWM 域亮度系数：从 1% 按 lv^0.7 升到 1.0（吃满固件硬限）。

    1% 是**起点**而不是「低音量段固定不变」的保底平台 —— 后者会让人觉得
    声音很小灯却很亮。旧版线性 lv 在低段只有 2~7/255，等亮度可见时颗数
    已铺开 5 颗，看着像突然亮一片；用 <1 的指数把前端抬起来。
    上限不再在 host 端打折：白色封面满档发 255/255，固件
    setBrightness(128) 是唯一硬限。media 帧和终端面板共用；
    调用方必须先把封面色过 gamma。
    """
    lv = max(0.0, min(1.0, level))
    return (RENDER_BRIGHT_FLOOR
            + (RENDER_BRIGHT_MAX - RENDER_BRIGHT_FLOOR) * lv ** RENDER_BRIGHT_GAMMA)


# ---- 环境彩虹：没有 SMTC 音乐信息时（打游戏 / 系统音效）----
# 颜色是固定的 60 段 300° 渐变，静止不流动、不呼吸；**默认全灭**，
# 电平决定「亮几颗」——和放歌完全同一条曲线、同一套快起慢落、同一个渐入。
# 亮度也走 render_brightness() 的 1% -> 100% 曲线 + 120ms 低通（与放歌共用
# _bright_value）。旧版乘 2.0 是为了把纯 HSV 彩虹抬回 75%，但放歌上限放开到
# 1.0 之后再乘 2 会全程被 clamp 到满亮、把曲线形状压平，所以增益归 1。
# 基色已经是 PWM 域，raw 直出不过 gamma，也不需要 with_glow 补暗灯。
AMBIENT_HUE_SPAN = 300.0          # 不铺满 360°，首尾两颗不会撞成同一个红
AMBIENT_SAT = 0.88
AMBIENT_BRIGHT_GAIN = 1.0         # 与放歌共用同一条曲线，不再额外放大
# 静音 -> 有声的去抖：连续超门限这么久才允许点亮。系统零碎提示音 / 输出端点
# 刚枚举时的一两帧毛刺不该让第一颗灯冒出来；持续的游戏 / 视频音效照常跟上。
# 想和放歌完全同一瞬间起步，把这里设 0（开机误触发由 BOOT_QUIET_SEC 兜住）。
AMBIENT_ON_DELAY = 0.4


def ambient_base():
    """环境彩虹的 60 颗基色：固定 300° 色相渐变，按物理位置铺、与时间无关。"""
    return [hsv_to_rgb(AMBIENT_HUE_SPAN * i / max(1, LED_COUNT - 1),
                       AMBIENT_SAT, 1.0) for i in range(LED_COUNT)]


def with_glow(rgb, ref, floor):
    """暗灯珠的最低可见亮度保底：按 ref 的色相比例把 rgb 至少抬到 floor。

    rgb = 最终 PWM 值；**ref 必须是感知域的封面色（未过 gamma）**。
    这里不能传 gamma_base：gamma 是 2.8 次方，会把通道差异放大，
    近中性略蓝的 (56,59,75) 过 gamma 成了 (4,4,8)，照这个比例补出来就是纯蓝。
    按感知比例放大、再做 GLOW_DESAT 轻度去饱和，才是「偏米白的浅蓝」。
    floor **必须由调用方按当前亮度给出**（1~RENDER_MIN_GLOW），不能传固定值：
    固定保底会让深色封面在整个音量范围内输出同一个亮度，变成固定平台；
    floor 也别定得太小（旧版 3/255 对 gamma 后 5/255 的暗灯根本不触发）。
    只在「逻辑上已点亮」的灯珠上调用，熄灭的不动；纯黑封面色没有色相可依，
    退化为中性灰。这样「亮了几颗」和「肉眼看见几颗」才对得上。
    """
    if max(rgb) >= floor:
        return rgb
    gray = max(ref)
    if gray <= 0:
        return (floor, floor, floor)
    k = floor / gray
    return tuple(min(255, max(0, round((v + (gray - v) * GLOW_DESAT) * k)))
                 for v in ref)


def mic_leds(in_use, level=0.0, reverse=False):
    """麦克风态的 60 颗颜色（**已经是最终 PWM 值**，调用方要按 raw 直出）。

    in_use=False -> 全灭（待机：灯带与板载 LED 都灭，完全静默）。
    in_use=True  -> 音量同时决定亮几颗、什么颜色、多亮；
                    低于 MIC_SOUND_GATE 一颗都不亮，只有真有声音才亮起来。
                    颜色沿亮起顺序从绿连续渐变到红（60 段，见 mic_hue）。
    """
    if not in_use:
        return [(0, 0, 0)] * LED_COUNT
    order = mic_order(reverse)
    out = [(0, 0, 0)] * LED_COUNT
    n = mic_led_count(level)
    bright = mic_brightness(level)
    whole, extra, fade = vu_steps(n)
    # 小数部分 = 正在长出来的「下一颗」渐入。旧写法把 frac 乘在已亮的
    # 最后一颗上（面板说 N+0.3 颗、实际只有 N 颗），后来又加了 frac>0.06
    # 迟滞，60 级精度被吞掉一截；现在严格逐级、无阈值。
    for i, idx in enumerate(order):
        if i >= whole + extra:
            break
        c = hsv_to_rgb(mic_hue(i), MIC_SAT, MIC_VALUE)
        k = bright * (fade if i == whole else 1.0)
        out[idx] = scale(c, k)
    return out


def diagnose_media():
    """列出系统里所有 SMTC 会话。不只看 current session——网易云常不是当前会话。"""
    if not HAS_MEDIA:
        print("  WinRT/Pillow 未装全，媒体源不可用")
        return

    async def run():
        mgr = await _MediaManager.request_async()
        sessions = list(mgr.get_sessions())
        cur = mgr.get_current_session()
        cur_id = cur.source_app_user_model_id if cur else None
        print(f"  会话总数: {len(sessions)}   系统当前会话: {cur_id}")
        if not sessions:
            print("  【空】没有任何播放器注册到系统媒体接口")
            return
        for i, s in enumerate(sessions):
            try:
                props = await s.try_get_media_properties_async()
                st = int(s.get_playback_info().playback_status)
                print(f"    [{i}] {s.source_app_user_model_id}")
                print(f"         标题: {props.title}   状态: {MediaWatcher.STATUS_NAME.get(st, st)}"
                      f"   封面: {'有' if props.thumbnail else '【无】'}")
            except Exception as e:
                print(f"    [{i}] 读取失败: {type(e).__name__}: {e}")

    asyncio.run(run())


# ============================================================
# 终端面板（ANSI 真彩色）
# ============================================================
WIDTH = 52                       # 面板内部宽度（不含边框）
RESET = "\033[0m"
ANSI_RE = re.compile(r"\033\[[0-9;]*m")

STATE_COLOR = {"media": (205, 110, 255), "mic": (90, 200, 110), "idle": (120, 120, 140),
               "ambient": (120, 180, 255)}
STATE_LABEL = {"media": "音乐电平", "mic": "麦克风电平", "idle": "空闲",
               "ambient": "环境彩虹"}


def enable_ansi():
    if os.name != "nt":
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)                      # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        k.SetConsoleMode(h, mode.value | 0x0004)     # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return True
    except Exception:
        return False


def _cw(c):
    return 2 if unicodedata.east_asian_width(c) in "WF" else 1


def vis_width(s):
    """可见宽度：去掉 ANSI 转义，中文/全角算 2 列"""
    return sum(_cw(c) for c in ANSI_RE.sub("", s))


def pad(s, width):
    return s + " " * max(0, width - vis_width(s))


def clip(s, width):
    """按可见宽度截断，超出部分用 … 代替（歌名经常超长）"""
    if vis_width(s) <= width:
        return s
    out, w = "", 0
    for c in s:
        c1 = _cw(c)
        if w + c1 > width - 1:
            break
        out += c
        w += c1
    return out + "…"


def bg(rgb, text="  "):
    r, g, b = rgb
    return f"\033[48;2;{r};{g};{b}m{text}{RESET}"


def fg(rgb, text):
    r, g, b = rgb
    return f"\033[38;2;{r};{g};{b}m{text}{RESET}"


def bar(pct, width=20, rgb=None, full="█", empty="░"):
    n = int(round(width * max(0.0, min(100.0, pct)) / 100.0))
    body = full * n + empty * (width - n)
    return fg(rgb, body) if rgb else body


def mmss(sec):
    sec = int(max(0, sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


class Display:
    def __init__(self, enabled=True):
        self.enabled = bool(enabled)
        # pythonw.exe 下 sys.stdout 是 None，先判空再问 isatty，否则后台模式一启动就崩
        self.ansi = (bool(enabled) and sys.stdout is not None
                     and enable_ansi() and sys.stdout.isatty())
        self._lines = 0

    # ---------- 内部 ----------
    def _row(self, content):
        return "│ " + pad(content, WIDTH) + " │"

    def _sep(self, left="├", right="┤"):
        return left + "─" * (WIDTH + 2) + right

    def _flush(self, lines):
        if self._lines:
            sys.stdout.write(f"\033[{self._lines}A\033[J")   # 光标回到面板顶部再重绘
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        self._lines = len(lines)

    # ---------- 面板 ----------
    def render(self, mon, fps):
        if not self.enabled:
            return                       # 后台模式：一个字节都不写，日志才干净
        if not self.ansi:
            self._render_plain(mon, fps)
            return

        st = mon.state
        col = STATE_COLOR.get(st, (160, 160, 160))
        label = STATE_LABEL.get(st, st)
        if st == "mic" and mon.mic:
            if mon.mic.in_use:
                # 头部圆点跟着当前电平走：绿 -> 黄 -> 橙 -> 红
                lv = mon.level.value
                col = hsv_to_rgb(mic_hue(max(0.0, mic_led_count(lv) - 1)),
                                 MIC_SAT, 0.90)
            else:
                # 待机灯带全灭，标题换掉；圆点沿用 mic 态绿色（灯珠全黑，取不出颜色）
                label = "待机全灭"
        L = ["┌" + "─" * (WIDTH + 2) + "┐"]

        right = f"{fps:4.1f} fps"
        head = f"{fg(col, '●')} {label}"
        L.append(self._row(pad(head, WIDTH - vis_width(right)) + right))
        L.append(self._sep())

        m = mon.media
        if st == "mic" and mon.mic:
            busy = mon.mic.in_use
            if busy:
                lv = mon.level.value
                tag = (f"电平 {mic_led_count(lv):.1f}/{LED_COUNT} · "
                       f"亮度 {mic_brightness(lv):>3.0%} · 峰值 {mon.level.peak:.3f}")
            else:
                tag = "待机 · 全静默（灯带与板载都灭）"
            line = f"麦克风 {bg(col, '  ')} {tag}"
            if busy and mon.mic.apps:
                who = "、".join(mon.mic.apps[:2])
                line += "  " + clip(who, WIDTH - vis_width(line) - 2)
            L.append(self._row(line))
        elif st == "ambient":
            lv = mon.render_level.value
            # 与放歌那行同一个口径：颗数走 render_led_count，亮度显示实际发出的
            # 平滑值（_bright_value）而不是瞬态目标，乘上彩虹的整体亮度增益。
            shown_b = getattr(mon, "_bright_value", None)
            if shown_b is None:
                shown_b = render_brightness(lv)
            L.append(self._row(clip(
                f"♪ 环境彩虹 {render_led_count(lv):.1f}/{LED_COUNT} 颗 · "
                f"亮度 {shown_b * AMBIENT_BRIGHT_GAIN:.0%} · "
                f"峰值 {mon.render_level.peak:.3f}", WIDTH)))
        elif m and m.available:
            if m.title:
                L.append(self._row("♪   " + clip(f"{m.title}  —  {m.artist}".strip(" —"), WIDTH - 4)))
            else:
                L.append(self._row("♪   （没有在播放）"))
            icon = "▶" if m.playing else "⏸"
            if m.duration > 0:
                # 只有播放器真的上报了时间轴才画进度条（浏览器播视频一般有）
                pos = m.position if m.position > 0 else m.elapsed
                ratio = min(100.0, pos / m.duration * 100.0)
                L.append(self._row(f"{icon}  {bar(ratio, 26, col)}  "
                                   f"{mmss(pos)} / {mmss(m.duration)}"))
            elif m.playing:
                # 网易云不上报时长，显示 "00:00 (时长未知)" 纯属噪音，直接省掉
                L.append(self._row(f"{icon}  播放中"))
            else:
                L.append(self._row(f"{icon}  已暂停"))
        else:
            L.append(self._row("♪   媒体源未启用"))
        L.append(self._sep())

        if st == "media" and m and m.available and m.palette:
            # 色块按权重给宽度，但 10 色时可能撑破 52 列边框 —— 按可见宽度
            # 自动收紧倍率，每色最短 2 列，保证整行永远放得下。
            scale = 9
            while True:
                blocks = "".join(bg(c, "  " * max(1, round(w * scale)))
                                 for c, w in m.palette)
                row = f"配色 {blocks}  {len(m.palette)} 色"
                if vis_width(row) <= WIDTH or scale <= 1:
                    break
                scale -= 1
            L.append(self._row(row))
        rm = getattr(mon, "render_meter", None)
        if st == "media" and rm and rm.available:
            lv = mon.render_level.value
            # 放歌颗数走 render_led_count() 的幂曲线，与实际灯效帧、面板文字一致；
            # 不能用麦克风 VU 的 mic_led_count()（那边有 0.02 门限）。
            # 亮度显示实际发出的平滑值，别显示瞬态目标，否则和灯珠对不上。
            shown_b = getattr(mon, "_bright_value", None)
            if shown_b is None:
                shown_b = render_brightness(lv)
            L.append(self._row(f"输出 {render_led_count(lv):.1f}/{LED_COUNT} 颗  "
                               f"亮度 {shown_b:.0%}  "
                               f"峰值 {mon.render_level.peak:.3f}"))
        # 「灯珠」实时色块已移除：60 颗逐帧刷色块既占面板又看不清，
        # 上面「输出 / 亮度 / 峰值」这行数字已经足够表达状态。
        if getattr(mon, "status_led", False):
            # 板载 LED 此刻在干什么 —— 平时全灭，只在事件瞬间闪几下
            L.append(self._row("板载  " + getattr(mon, "status_led_note", "灭 · 静默")))
        L.append("└" + "─" * (WIDTH + 2) + "┘")

        self._flush(L)

    def _render_plain(self, mon, fps):
        """没有 ANSI 时退化成单行，免得画出一堆乱码"""
        parts = [f"{mon.state}"]
        if mon.state == "mic" and mon.mic:
            if mon.mic.in_use:
                lv = mon.level.value
                parts.append(f"麦克风 {mic_led_count(lv):.1f}/{LED_COUNT} 颗 "
                             f"{mic_brightness(lv):.0%} 亮度")
            else:
                parts.append("麦克风 待机 全灭")
        if mon.media and mon.media.available and mon.media.title:
            t = clip(mon.media.title, 20)
            parts.append(f"♪ {t} "
                         f"{mmss(mon.media.duration and mon.media.position or mon.media.elapsed)}")
        sys.stdout.write("\r  " + "  ".join(parts) + f"  {fps:.0f}fps   ")
        sys.stdout.flush()

    def finish(self):
        """退出前把光标移到面板下方，别让后续输出盖在面板上"""
        if self.ansi and self._lines:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._lines = 0


# ============================================================
# 灯带输出（串口协议，与固件保持一致）
# ============================================================
HDR0, HDR1 = 0xA5, 0x5A
CMD_SET_ALL, CMD_BRIGHTNESS, CMD_HEARTBEAT, CMD_OFF, CMD_HANDSHAKE = 0x01, 0x03, 0x04, 0x06, 0x10
CMD_STATUS_LED = 0x07
CMD_STATUS_PULSE = 0x08
# v6 固件 = 180B 逐颗帧 + 17B 握手身份帧；v4 是 90B/30 组，帧长不兼容。
# 身份帧：[0]=版本 [1..12]=型号 [13..16]=芯片ID(小端)。
# 主机逐个串口探测，只认型号匹配的那个，所以不用写死 COM 号。
EXPECTED_FIRMWARE = 6
# 现役板子：WeMOS D1 mini（数据脚 D2 / GPIO4），型号字符串 "D1MINI-LED60"。
# 历史还有一块 ESP-01S（数据脚 GPIO0，型号 "ESP01S-LED60"）：协议逐字节相同，
# 所以仍然认它，插回来灯效照常；那块板子和固件已归档，不再维护。
# 型号必须是 12 字节（IDENTITY_LEN 才是 17）；加新板子只要往这里追加一条。
# 顺序有意义：第 0 条是「识别不到设备时」的兜底显示名，所以现役板子放最前。
DEVICE_MODELS = (b"D1MINI-LED60", b"ESP01S-LED60")
DEVICE_MODEL_LEN = 12
DEVICE_MODEL = DEVICE_MODELS[0]       # 兜底显示用：识别不到设备时的默认型号名
IDENTITY_LEN = 17
# 板载 LED（GPIO2 / D4）的常驻灯态，取值必须跟固件里的 STATUS_* 一致。
# 现在只用 OFF（待机静默）/ ON（麦克风在用）；固件 BLINK(2) 不用。
# 事件脉冲走 0x08，失联呼吸由固件自己接管。
STATUS_LED_OFF, STATUS_LED_ON, STATUS_LED_BLINK = 0, 1, 2
# 事件提示：闪几下。三个事件给不同下数，不用看屏幕就知道刚发生了什么。
# 切歌 = SMTC 标题变了（不代表封面已到）；封面就绪 = 封面字节哈希真的变化、
# 取色更新完成 —— 网易云这类播放器可能滞后好几秒，单独报一声才知道什么时候拿到。
PULSE_TRACK = 2            # 切歌（标题变化）
PULSE_STATE = 3            # 状态切换（media / mic / idle 之间）
PULSE_COVER = 1            # 封面/SMTC 信息真正取到
# 两次脉冲之间的最小间隔：连按「下一首」时别闪成一片频闪灯
PULSE_GUARD = 0.8
# 事件发生后，面板上把这行字保留多久
NOTE_HOLD = 1.5
# 渲染帧率 50Hz：一帧 185B（60 颗 × 3B + 5B 帧头/CRC），
# 50 × 185 × 10bit = 92500 bit/s，占 115200 的 80.3%。
# 100Hz 就是 185000 bit/s（160%），直接超带宽 —— 逐颗控色下 50Hz 是硬上限。
# 单帧串口耗时 16.1ms + 60 颗 show() 1.8ms ≈ 17.9ms，20ms 帧间隔余量约 2ms；
# 关中断期间最多落 ~21 字节到 UART FIFO（128B），不会丢帧。
# 若实测有迟滞/丢帧，把 FRAME_HZ 降到 40；平滑常数按秒定义，改帧率不改手感。
FRAME_HZ = 50
FRAME_INTERVAL = 1.0 / FRAME_HZ
# 固件侧全局亮度仍发 255：v5 固件会在 CMD_BRIGHTNESS 里 clamp 到 128（50% 硬限），
# 这是 60 颗灯带的电流天花板。host 侧不额外打折，避免两道相乘把亮度压没。
# 60 颗全白理论 3.6A；host 上限放开到 255 后，白色封面满档 / 白色装饰常亮
# 都是 255×50% ≈ 1.8A，VU 峰值 80% ≈ 1.44A，外加板子自身耗电
# —— 必须外接 5V >=2A（留余量建议 3A），别只靠 USB-TTL 取电。
DEFAULT_BRIGHTNESS = 255
# host 侧输出上限（0~1），在 gamma 之前乘到每颗灯上 —— 只有降级封面呼吸受它限制。
# 两种声音驱动灯效是例外：亮度是 0~255 的最终 PWM 值、raw 直出不过 gamma
# （见 MIC_BRIGHT_STOPS / render_brightness / set_all(raw=True)）。
# 放歌先把封面色过 gamma（避免泛白过曝），满档白色封面发 255/255，
# 由固件 128 硬限到实际 50%；VU 峰值 80%。
# 70% 感知亮度对应 PWM gamma(178)=93，8 颗约 173mA，加板子约 250mA，离 USB 500mA 还有余量。
MAX_LEVEL = 0.70

# ---------------- 呼吸参数 ----------------
BREATHE_PERIOD = 4.0          # 一次完整呼吸的秒数（亮 -> 暗 -> 亮）
BREATHE_DEPTH = 0.40          # 呼吸幅度：亮度在 (1-depth) ~ 1 之间起伏
MEDIA_FALLBACK_DELAY = 1.5    # 音乐停多久才熄灯（防切歌/暂停空档闪灭）
# 开机静默期：自启进程刚起来的这段时间内强制全灭，不管输出端点读到什么。
# 任务计划是 LogonTrigger + Delay 20s，脚本再 --wait-port（最多 30s，实际
# 串口一握手成功就返回），Windows 登录音 / 通知音 / 浏览器自动播放常在这段
# 窗口里冒出来，ambient 会当成「有声音」亮第一颗。只在 --wait-port > 0
# （=自启命令行）时启用，前台手动跑不受影响。
# 这不是「监控开关机」：Windows 不给后台 pythonw 发可靠的关机通知，
# 真正的兜底是固件 fail-safe 全灭（见 .ino 的 CMD_BRIGHTNESS / setup）。
BOOT_QUIET_SEC = 12.0
# 输出平滑时间常数。只用来让换歌时的颜色柔和过渡，不能太大 —— 否则会把呼吸的振幅削掉：
# 一阶低通对周期 T 的正弦，振幅保留 1/√(1+(2πτ/T)²)。τ=0.35s 时 4s 呼吸只剩 88%、
# 2s 呼吸只剩 67%；τ=0.15s 则是 97% / 90%，换歌过渡也还够柔和。
SMOOTH_TAU = 0.15

# WS2812 视觉线性极差，不做 gamma 校正暗部会跳阶
GAMMA = [min(255, round(255.0 * ((i / 255.0) ** 2.8))) for i in range(256)]


def crc8(data: bytes) -> int:
    c = 0x00
    for byte in data:
        c ^= byte
        for _ in range(8):
            c = ((c << 1) ^ 0x07) & 0xFF if (c & 0x80) else (c << 1) & 0xFF
    return c


def build_frame(cmd: int, payload: bytes = b"") -> bytes:
    body = bytes([cmd, len(payload)]) + payload
    return bytes([HDR0, HDR1]) + body + bytes([crc8(body)])


def parse_identity(payload):
    """解析握手回应；不匹配返回 None（不误连别的设备）。

    v6 = 17B 完整身份帧（型号 + 芯片序列号），型号在 DEVICE_MODELS 里任一条都认。
    现役是 D1 mini（D1MINI-LED60）；旧的 ESP-01S（ESP01S-LED60）协议逐字节相同，
    只是型号字符串和数据脚不同，所以仍兼容，插回来也不会被误判成陌生设备。
    v5 = 只回 1B 版本号：为了「还没烧 v6 的板子插回来也能正常亮灯」而兼容，
    但标 legacy=True，Web 会提示烧录后才有自动识别串口的能力。
    """
    if not payload:
        return None
    if len(payload) >= IDENTITY_LEN and payload[0] == EXPECTED_FIRMWARE:
        model = payload[1:1 + DEVICE_MODEL_LEN]
        if model in DEVICE_MODELS:
            chip = int.from_bytes(payload[13:17], "little")
            return {"version": payload[0],
                    "model": model.decode("ascii"),
                    "serial": f"{chip:08X}",      # ESP8266 芯片 ID，每片唯一
                    "legacy": False}
    if len(payload) == 1 and payload[0] == 5:
        return {"version": 5, "model": "UNKNOWN", "serial": "", "legacy": True}
    return None


def candidate_ports(preferred=None):
    """候选串口：指定端口优先，其次 CH340/USB-SERIAL，最后其余串口。

    preferred 为 None / 'auto' / 空则全自动。指定端口不在枚举列表里也保留
    （刚插上还没枚举完时能先试一次）。返回去重后的端口名列表。
    """
    try:
        enumerated = list(list_ports.comports())
    except Exception:
        enumerated = []
    out = []
    if preferred and str(preferred).strip().lower() not in ("auto", ""):
        out.append(str(preferred).strip())
    ch340, others = [], []
    for p in enumerated:
        desc = (p.description or "").lower()
        (ch340 if ("ch340" in desc or "usb-serial" in desc
                   or "usb serial" in desc) else others).append(p.device)
    for d in ch340 + others:
        if d not in out:
            out.append(d)
    return out


# ---------------- 设备档案：序列号绑定 ----------------
# 为什么需要这个文件：握手只能证明「这是一块本项目固件」，不能证明「这是我这条灯带」。
# 同时插着两块同型号板时，谁先枚举到就控制谁 —— 会控错别人的灯。所以第一次连接
# 时把芯片序列号记下来（device.json），以后只认这个序列号：
#   - 换了 USB 口（端口漂移）→ 按序列号重新定位，端口只是缓存，随时更新；
#   - 换了板子 / 那台没插 → 明确报「绑定的设备不在场」，不去静默接管另一台。
DEVICE_PROFILE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "device.json")


def load_device_profile(path=DEVICE_PROFILE_FILE):
    """读 device.json -> {serial, port, model, version, bound_at, updated_at}

    文件不存在 / JSON 坏了 / 里面没有 serial，一律当成「未绑定」返回 {}，
    不让一个坏文件把启动卡死（最差退回首次运行的询问流程）。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    serial = str(data.get("serial") or "").strip().upper()
    if not serial:
        return {}
    return {
        "serial": serial,
        "port": str(data.get("port") or "").strip(),
        "model": str(data.get("model") or ""),
        "version": data.get("version"),
        "bound_at": str(data.get("bound_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
    }


def save_device_profile(device, port, path=DEVICE_PROFILE_FILE):
    """把「这台设备的序列号 + 当前端口」写进 device.json（原子替换）。

    port 只是缓存：真正决定身份的是序列号。重新绑定另一台时 bound_at 刷新，
    同一台只是换了端口则保留首次绑定时间，方便日后看「什么时候认的这块板」。
    """
    serial = str((device or {}).get("serial") or "").strip().upper()
    if not serial:
        return False              # v5 固件没有身份证，没法绑定
    old = load_device_profile(path)
    now = _now_text()
    data = {
        "serial": serial,
        "port": str(port or "").strip(),
        "model": str(device.get("model") or DEVICE_MODEL.decode("ascii")),
        "version": device.get("version") or EXPECTED_FIRMWARE,
        "bound_at": (old.get("bound_at")
                     if (old.get("serial") == serial and old.get("bound_at"))
                     else now),
        "updated_at": now,
    }
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[设备] 写 device.json 失败：{e}")
        return False
    return True


def clear_device_profile(path=DEVICE_PROFILE_FILE):
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        print(f"[设备] 删除 device.json 失败：{e}")
        return False


def note_device_port(device, port, profile=None, path=DEVICE_PROFILE_FILE):
    """端口漂移时更新档案里的 port；端口没变就一个字节都不写。

    换 USB 口后 COM 号会变，但序列号不变 —— 这里只改缓存字段，
    身份判断永远走 serial，所以写失败也不影响能不能连上。
    """
    prof = profile if profile is not None else load_device_profile(path)
    serial = str((device or {}).get("serial") or "").strip().upper()
    if not prof or not serial or prof.get("serial") != serial:
        return False
    if prof.get("port") == port:
        return False
    return save_device_profile(device, port, path=path)


def device_text(dev, with_port=True):
    """一行描述一台设备；日志、--list-devices、面板共用同一套措辞。"""
    if not dev:
        return "—"
    if dev.get("legacy"):
        return ("v5 固件（无身份证）"
                + (f" @ {dev.get('port')}" if with_port and dev.get("port") else ""))
    s = (f"{dev.get('model') or DEVICE_MODEL.decode('ascii')} "
         f"v{dev.get('version')} · 序列号 {dev.get('serial') or '?'}")
    if with_port and dev.get("port"):
        s += f" @ {dev['port']}"
    return s


def _port_descriptions():
    try:
        return {p.device: (p.description or "") for p in list_ports.comports()}
    except Exception:
        return {}


def probe_devices(baud=115200, preferred=None, max_level=MAX_LEVEL,
                  timeout=0.9, only=None):
    """遍历候选串口逐个握手，返回**每个口**的探测结果。

    ok=True 的才是本项目灯带；失败项也一并返回（端口 + 原因），这样
    「一个串口都没有」和「有串口但都不是这块板」能区分开，报错才准确。
    每个口都要真的打开 → 握手 → 关闭，约 0.3s/口，所以只在启动和重连时扫。
    """
    descs = _port_descriptions()
    ports = [only] if only else candidate_ports(preferred)
    out = []
    for port in ports:
        item = {"port": port, "ok": False, "reason": "",
                "description": descs.get(port, ""),
                "model": "", "version": None, "serial": "", "legacy": False}
        try:
            st = LedStrip(port, baud, max_level, verbose=False)
        except Exception as e:
            item["reason"] = f"打不开：{type(e).__name__}: {e}"
            out.append(item)
            continue
        try:
            if st.handshake(timeout=timeout):
                dev = st.device or {}
                item.update(ok=True,
                            model=dev.get("model", ""),
                            version=dev.get("version"),
                            serial=dev.get("serial", ""),
                            legacy=bool(dev.get("legacy")))
            else:
                item["reason"] = "无回应或身份不符（不是本项目 v6 固件）"
        except LinkLost as e:
            item["reason"] = f"握手时断链：{e}"
        finally:
            st.close()
        out.append(item)
    return out


def _prompt_device(devices, log=print, input_fn=None):
    """多台时可交互地问一句选哪台；回车默认第 1 台，q 放弃。

    只在**前台有控制台**时才会走到这里（后台 pythonw 没有 stdin，问了会卡死），
    所以直接 input() 是安全的；input_fn 只是为了自测时能注入假输入。
    """
    input_fn = input_fn or input
    log("")
    log(f"发现 {len(devices)} 台可控的灯带，请选择要控制的那一台：")
    for i, d in enumerate(devices, 1):
        extra = f"   {d['description']}" if d.get("description") else ""
        log(f"  [{i}] {d['port']:<7} {device_text(d, with_port=False)}{extra}")
    log(f"  输入编号 1-{len(devices)}（回车默认 1），q 放弃：")
    while True:
        try:
            raw = str(input_fn("  > ")).strip()
        except (EOFError, KeyboardInterrupt):
            log("")
            return None
        if not raw:
            return devices[0]
        if raw.lower() in ("q", "quit", "exit"):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(devices):
            return devices[int(raw) - 1]
        log(f"  请输入 1-{len(devices)} 之间的数字，或 q 放弃")


def choose_device(probes, profile=None, ask=False, log=print, input_fn=None):
    """从探测结果里决定到底控制哪一台。返回 (device, action, note)。

    action 说明这次是怎么定的，调用方据此决定要不要写 device.json：
      bound     绑定序列号命中（端口可能换了，按序列号找回）
      single    只有一台候选 —— 自动记住它
      picked    多台，用户刚选了一台
      fallback  多台但没法问（后台无控制台），暂用第一台，不写绑定
      missing   有绑定，但绑定的那台不在场（发现的是别的板子）
      none      没有可控制的候选
    """
    good = [d for d in probes if d.get("ok")]
    if not good:
        if not probes:
            return None, "none", "系统没有枚举到任何串口"
        return None, "none", "枚举到串口，但没有一台回本项目固件身份"

    bound = str((profile or {}).get("serial") or "").strip().upper()
    if bound:
        for d in good:
            if str(d.get("serial") or "").upper() == bound:
                return d, "bound", ""
        found = "、".join(f"{d['port']}({d.get('serial') or 'v5'})" for d in good)
        return None, "missing", (
            f"绑定的设备（序列号 {bound}）不在场，当前发现 {found}；"
            "不会去控制别的板子，插回原板或用 --select-device 重新绑定")

    if len(good) == 1:
        return good[0], "single", ""
    if ask:
        sel = _prompt_device(good, log=log, input_fn=input_fn)
        if sel is None:
            return None, "none", "已放弃选择设备（绑定未改动）"
        return sel, "picked", ""
    return good[0], "fallback", (
        f"发现 {len(good)} 台可控灯带，当前无法询问，暂用 {good[0]['port']}；"
        "运行 --select-device 可固定下来")


def apply_gamma(rgb):
    return tuple(GAMMA[max(0, min(255, int(v)))] for v in rgb)


def hsv_to_rgb(h: float, s: float, v: float):
    """h:0-360  s,v:0-1 -> (r,g,b) 0-255（demo 彩虹用）"""
    c = v * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = v - c
    if h < 60:      r, g, b = c, x, 0
    elif h < 120:   r, g, b = x, c, 0
    elif h < 180:   r, g, b = 0, c, x
    elif h < 240:   r, g, b = 0, x, c
    elif h < 300:   r, g, b = x, 0, c
    else:           r, g, b = c, 0, x
    return (round((r + m) * 255), round((g + m) * 255), round((b + m) * 255))


def scale(rgb, k):
    return tuple(max(0, min(255, int(c * k))) for c in rgb)


def lerp_rgb(cur, target, k: float):
    return tuple(int(c + (t - c) * k) for c, t in zip(cur, target))


def palette_to_leds(palette, n=LED_COUNT):
    """按权重把封面配色当作「色标」铺成连续渐变。

    旧版是硬分段（主色连续占 N 组、到下一段直接换色），60 颗灯带上就是
    一格一格的色块。现在每个颜色按权重占一段、色标放在段中心，
    相邻色标之间线性插值、两端向最近色标延伸，最后轻抹掉色标处的折点 ——
    和 spatial 一样是平滑过渡，仍能看出封面的配色比例。
    """
    if not palette:
        return [(0, 0, 0)] * n
    total = sum(w for _, w in palette) or 1.0
    xs, cs = [], []
    acc = 0.0
    for color, weight in palette:
        start = acc / total
        acc += weight
        end = acc / total
        xs.append((start + end) / 2 * (n - 1))
        cs.append(color)
    out = []
    for i in range(n):
        if i <= xs[0]:
            out.append(cs[0])
        elif i >= xs[-1]:
            out.append(cs[-1])
        else:
            picked = cs[-1]
            for k in range(len(xs) - 1):
                if xs[k] <= i <= xs[k + 1]:
                    t = (i - xs[k]) / max(1e-6, xs[k + 1] - xs[k])
                    picked = tuple(round(a + (b - a) * t)
                                   for a, b in zip(cs[k], cs[k + 1]))
                    break
            out.append(picked)
    smooth = _smooth_series(out, max(1, int(round(COVER_SMOOTH_GROUPS))))
    return [tuple(round(v) for v in c) for c in smooth]


def is_black_led(rgb):
    """这颗灯「看起来是黑的」吗：过完 gamma 后几乎没有光、且没有色相。

    判据放在最终 PWM 域，因为灯珠真正发出去的是 gamma 之后的值 ——
    归一化后的 (38,38,38) 灰 gamma 后只剩 (1,1,1)，肉眼就是黑的。
    饱和度高但很暗的颜色（深蓝）不算黑：它有色相，靠色相保底仍能看见。
    """
    if max(apply_gamma(rgb)) >= DARK_MAX_GAMMA:
        return False
    _, s, _ = colorsys.rgb_to_hsv(*[c / 255 for c in rgb])
    return s < DARK_MAX_SAT


def fill_dark_leds(base):
    """把「黑灯」换成左右最近非黑颜色的**线性插值**，渐变不被打断。

    旧版按位置轮转从候选池取色，填进去的颜色跟左右邻居无关 —— 在 60 颗
    连续渐变上会凭空插进一个跳变。现在按距离插值，黑位拿到的正好是两侧
    的过渡色，平滑性反而更好；两端之外只有单侧有颜色就沿用那一侧。
    整张封面全黑时取最亮那颗保留色相提亮，60 颗统一用（纯黑退化中性灰）。
    """
    base = list(base[:LED_COUNT])
    while len(base) < LED_COUNT:
        base.append(base[-1] if base else (0, 0, 0))
    keep = [i for i, c in enumerate(base) if not is_black_led(c)]
    if len(keep) == len(base):
        return base
    if not keep:
        brightest = max(base, key=lambda c: max(apply_gamma(c)))
        h, s, _ = colorsys.rgb_to_hsv(*[c / 255 for c in brightest])
        r, g, b = colorsys.hsv_to_rgb(h, s, DARK_FALLBACK_VALUE)
        c = (round(r * 255), round(g * 255), round(b * 255))
        return [c if not is_black_led(c) else (89, 89, 89)] * LED_COUNT

    out = list(base)
    for i in range(LED_COUNT):
        if i in keep:
            continue
        left = next((k for k in reversed(keep) if k < i), None)
        right = next((k for k in keep if k > i), None)
        if left is None:
            out[i] = base[right]
        elif right is None:
            out[i] = base[left]
        else:
            t = (i - left) / (right - left)
            out[i] = tuple(round(a + (b - a) * t)
                           for a, b in zip(base[left], base[right]))
    # 硬保证：两端都很暗时插值结果可能仍偏黑，用全局最亮的非黑色兜底
    fallback = max((base[k] for k in keep),
                   key=lambda c: max(apply_gamma(c)))
    if is_black_led(fallback):
        fallback = (89, 89, 89)
    for i, c in enumerate(out):
        if is_black_led(c):
            out[i] = fallback
    return out


class LinkLost(Exception):
    """串口断链：拔线 / 睡眠唤醒 / 驱动重枚举 / 写超时"""


class LedStrip:
    def __init__(self, port: str, baud: int = 115200, max_level=MAX_LEVEL,
                 led_count=LED_COUNT, expect_serial=None, verbose=True):
        self.port_name = port
        self.baud = baud
        # 只有一条 60 颗灯带：blank() 发 180B 全灭帧（v5 逐颗独立控色）。
        self.led_count = led_count
        self.brightness = None
        self.max_level = max(0.0, min(1.0, max_level))
        self._status_led = None      # 上次发过的板载 LED 灯态（None=未知，重连后要重发）
        self.device = None           # 握手成功后记录 {version, model, serial}
        # 绑定校验：给了 expect_serial 就只认这一片芯片，别的同型号板子一律跳过。
        # 这是「不控制错设备」的唯一手段 —— 型号能伪造（都是一样的固件），
        # 芯片 ID 是出厂烧死的，改不了。
        self.expect_serial = (str(expect_serial).strip().upper() or None
                              if expect_serial else None)
        self.verbose = verbose       # 批量探测时关掉，别把每个口的握手日志都刷出来
        self.last_identity = None    # 最近一次握手读到的身份（含被跳过的），报错用
        self.ser = None
        self.open()

    def open(self):
        """打开（或重开）串口"""
        self.ser = serial.Serial(self.port_name, baudrate=self.baud,
                                 timeout=0.3, write_timeout=0.5)
        time.sleep(0.2)          # CH340 打开后有个复位窗口，等一下再说话
        self.ser.reset_input_buffer()

    def close(self):
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.ser = None

    def _write(self, frame: bytes):
        """所有写入统一走这里，失败一律转成 LinkLost 交给上层去重连"""
        try:
            self.ser.write(frame)
        except Exception as e:
            raise LinkLost(f"{type(e).__name__}: {e}") from e

    def handshake(self, timeout: float = 1.2) -> bool:
        """发握手帧读回 17B 身份帧，校验「型号 + 版本」，并（若设置了）
        校验芯片序列号是否是绑定的那一台。

        按 LEN 收完整帧，兼容旧 v5 的 1B 回应（会判为身份不符）。
        返回 False 表示这个口不是「要控制的那台灯带」（不是本项目固件、
        或序列号对不上），调用方应换下一个候选口。
        """
        try:
            self.ser.reset_input_buffer()
            self.ser.write(build_frame(CMD_HANDSHAKE))
            deadline = time.time() + timeout
            buf = bytearray()
            while time.time() < deadline:
                chunk = self.ser.read(self.ser.in_waiting or 1)
                if not chunk:
                    continue
                buf += chunk
                while True:
                    pos = buf.find(bytes([HDR0, HDR1]))
                    if pos < 0:
                        if len(buf) > 1:
                            del buf[:-1]         # 留住可能是帧头的最后一个字节
                        break
                    if len(buf) < pos + 4:       # 至少要 CMD + LEN
                        break
                    ln = buf[pos + 3]
                    end = pos + 4 + ln + 1       # +1 是 CRC
                    if len(buf) < end:
                        break
                    body = bytes(buf[pos + 2:pos + 4 + ln])   # CMD+LEN+PAYLOAD
                    crc = buf[pos + 4 + ln]
                    del buf[:end]
                    if body[0] != CMD_HANDSHAKE or crc8(body) != crc:
                        continue
                    dev = parse_identity(body[2:2 + ln])
                    if dev:
                        self.last_identity = dev
                        # 绑定校验放在最前面：型号对得上不代表是「我这条灯带」
                        if self.expect_serial:
                            if dev["legacy"]:
                                if self.verbose:
                                    print(f"  [跳过] {self.port_name} 是 v5 固件，"
                                          "没有身份证，无法确认是不是绑定的那一台")
                                return False
                            if str(dev["serial"]).upper() != self.expect_serial:
                                if self.verbose:
                                    print(f"  [跳过] {self.port_name} 序列号 "
                                          f"{dev['serial']}，绑定的那台是 "
                                          f"{self.expect_serial}")
                                return False
                        self.device = dev
                        if dev["legacy"]:
                            if self.verbose:
                                print(f"  [警告] {self.port_name} 是 v5 固件，"
                                      "没有设备身份证；自动识别串口不可用，"
                                      "请跑 flash_d1mini.ps1 烧 v6")
                        elif self.verbose:
                            print(f"  握手成功：{dev['model']} v{dev['version']} "
                                  f"序列号 {dev['serial']} @ {self.port_name}")
                        return True
                    if self.verbose:
                        print(f"  [身份不符] {self.port_name} 不是本项目 v"
                              f"{EXPECTED_FIRMWARE} 灯带，换下一个串口")
                    return False
        except Exception as e:
            raise LinkLost(f"握手时断链：{type(e).__name__}: {e}") from e
        if self.verbose:
            print("  握手失败：没收到固件回应"
                  "（确认烧的是本项目固件，且串口监视器没开着）")
        return False

    def set_all(self, rgb_list, raw=False):
        """raw=True：rgb_list 已是最终 PWM 值（0~255），直接发，绕过 gamma 与 max_level。

        声音驱动灯效（放歌封面灯 / 麦克风 VU）必须用这个模式：它们给的
        1%~100% / 1.2%~80% 是「最终 PWM 值」，过一遍 gamma 会把 1% 压成 0/255、
        10% 压成约 0.4/255，肉眼全黑。降级封面呼吸用默认 False，
        走 gamma + 70% 上限；待机全灭走哪条都一样。
        """
        payload = bytearray()
        for rgb in rgb_list:
            if raw:
                payload += bytes(tuple(max(0, min(255, int(v))) for v in rgb))
            else:
                # 上限乘在 gamma 之前：gamma 是「感知亮度 → PWM」的映射，
                # 所以乘在它前面才是真的把亮度降到 70%，而不是把 PWM 砍掉 70%
                payload += bytes(apply_gamma(scale(rgb, self.max_level)))
        self._write(build_frame(CMD_SET_ALL, bytes(payload)))

    def set_brightness(self, value: int):
        self.brightness = max(0, min(255, value))
        self._write(build_frame(CMD_BRIGHTNESS, bytes([self.brightness])))

    def set_status_led(self, mode: int):
        """设定板载 LED 的常驻灯态（0=灭 1=常亮 2=慢闪）。只表达状态，不参与渲染帧，
        所以带缓存：值没变就一个字节都不发，串口带宽留给灯带。"""
        mode = int(mode)
        if mode == self._status_led:
            return
        self._status_led = mode
        self._write(build_frame(CMD_STATUS_LED, bytes([mode])))

    def pulse(self, times: int):
        """板载 LED 短闪 times 下后自动熄灭 —— 事件提示
        （封面就绪 1 / 切歌 2 / 状态切换 3）。

        和常驻灯态不同，这里绝不能缓存：同一个事件反复发生就得反复闪。
        闪的节奏由固件按毫秒自己走，不受主循环 50Hz 帧率的限制。"""
        times = max(1, min(10, int(times)))
        self._write(build_frame(CMD_STATUS_PULSE, bytes([times])))

    def blank(self):
        """把灯带钉死在全灭 —— 所有「刚启动 / 刚连上 / 刚重连」路径的第一条指令。

        CMD_OFF 让固件清掉 pixels 里残留的关机前最后一帧、把 currentLevel 压到 0；
        再补一帧全 0 的 SET_ALL，即使固件只清亮度不清数据，缓冲区也被覆盖干净。
        ★ 必须先 blank 再发 CMD_BRIGHTNESS：后者会恢复亮度并 show()，
          顺序反了就把旧颜色原样点亮（「开机后中间亮一颗」的真凶）。
        板载 LED 一并灭，别在开机时空闪。
        """
        self._write(build_frame(CMD_OFF))
        self._write(build_frame(CMD_SET_ALL, bytes(self.led_count * 3)))
        self.set_status_led(STATUS_LED_OFF)

    def off(self):
        try:
            self._write(build_frame(CMD_OFF))
            self.set_status_led(STATUS_LED_OFF)
            time.sleep(0.05)
        except Exception:
            pass

    # ---------- 断线重连 ----------

    def reconnect(self, stop_event=None, max_delay: float = 30.0,
                  log=print, progress=None) -> bool:
        """指数退避重连，每轮遍历所有候选串口并校验固件身份。

        原来的 find_port() 只按 CH340 描述挑第一个，多个 CH340 在线时会挑错；
        现在每个口都发握手帧，只认型号/版本匹配的那一条灯带；设了
        expect_serial 时连序列号也要对上 —— 插的如果是**另一块**同型号板子，
        宁可不连也不去控制它。
        progress(attempt, delay, error, found_port) 每次失败回调一次。
        """
        if self.expect_serial:
            log(f"  重连只认序列号 {self.expect_serial}（换 USB 口会自动重新定位）")
        delay, attempt = 1.0, 0
        while not (stop_event and stop_event.is_set()):
            attempt += 1
            ports = candidate_ports(self.port_name)
            if not ports:
                log(f"  未枚举到串口（第 {attempt} 次），{delay:.0f}s 后重试…")
                if progress:
                    progress(attempt, delay, "未找到任何串口", None)
            for port in ports:
                try:
                    self.close()
                    self.port_name = port
                    self.open()
                    if not self.handshake():       # 身份不符就换下一个口
                        self.close()
                        err = f"{port}: 握手/身份校验不通过"
                        log(f"  {err}（第 {attempt} 次）")
                        if progress:
                            progress(attempt, delay, err, port)
                        continue
                    log(f"  重连成功（第 {attempt} 次）：{port}")
                    # 换 USB 口后 COM 号变了，把新端口记回 device.json
                    note_device_port(self.device, port)
                    return True
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"
                    log(f"  重连失败（第 {attempt} 次，{port}）：{err}")
                    if progress:
                        progress(attempt, delay, err, port)
            end = time.time() + delay
            while time.time() < end:
                if stop_event and stop_event.is_set():
                    return False
                time.sleep(0.2)
            delay = min(delay * 2, max_delay)
        return False

    def resume(self) -> bool:
        """重连后恢复运行时状态：重新握手 + 清空灯带 + 重放亮度"""
        self._status_led = None          # 固件可能刚重启，板载灯态缓存作废，必须重发
        ok = self.handshake()
        # 休眠唤醒 / 拔线重插时固件可能没断电，pixels 里还是断链前那一帧。
        # 先 blank 再恢复亮度，别让旧颜色被 CMD_BRIGHTNESS 复活。
        self.blank()
        if self.brightness is not None:
            self.set_brightness(self.brightness)
        return ok


# ============================================================
# 主控
# ============================================================
class Monitor:
    """
    四个状态，优先级从高到低：
      mic      麦克风被占用 -> 60 段绿->红电平表 + 板载常亮（**压过放歌**）
      media    有音乐在播且麦克风没占用 -> 铺封面配色，输出峰值决定亮几颗/多亮
      ambient  无 SMTC 曲目、麦克风没占用、输出端点可用 -> 环境彩虹，默认全灭
      idle     麦克风检测不可用且输出端点也读不到 -> 全灭（基本只有非 Windows）

    麦克风在用是状态提示，优先级高于氛围灯效；代价是常驻占麦的 App 会让
    封面 / 彩虹长期不出现。切歌/暂停不立刻熄灯，留 MEDIA_FALLBACK_DELAY 的缓冲，
    但麦克风占用会直接绕过这段缓冲。注册表占用和电平峰值在所有状态下都持续轮询。
    """

    def __init__(self, app_filter=None, cover_layout="spatial",
                 breathe_period=BREATHE_PERIOD, breathe_depth=BREATHE_DEPTH,
                 mic=True, mic_reverse=False, status_led=True,
                 mic_full_peak=MIC_FULL_PEAK, render_full_peak=RENDER_FULL_PEAK,
                 render_attack_tau=RENDER_LEVEL_ATTACK_TAU,
                 render_release_tau=RENDER_LEVEL_RELEASE_TAU,
                 boot_quiet=0.0, mode=None):
        self.cover_layout = cover_layout
        # 空闲模式控制器（HTTP 面板与配置文件共用同一个对象）
        self.mode = mode if mode is not None else ModeController()
        self._mode_polled = 0.0
        self._live_at = 0.0
        self.breathe_period = max(0.2, breathe_period)
        self.breathe_depth = max(0.0, min(1.0, breathe_depth))
        self.status_led = status_led      # 板载 LED 状态指示 + 事件提示（--no-status-led 可关）
        self._prev_state = None           # 上一次的灯效状态：用来发现「状态切换」
        self._prev_track = None           # 上一首曲子：用来发现「切歌」
        self._prev_cover_updates = 0      # 上次看到的封面更新计数
        self._last_track_change_at = 0.0  # 上次检测到切歌的时刻：判断封面是否滞后
        self._pulse_guard_until = 0.0     # 脉冲冷却到期时刻，防止连按「下一首」闪成一片
        self._note = "灭 · 静默"          # 面板「板载」那一行：事件文案
        self._note_until = 0.0
        self._status_note = "灭 · 待机静默"   # 常驻状态文案

        self.media = MediaWatcher(app_filter)
        self.mic = MicWatcher() if mic else None
        self.meter = MicLevelMeter() if mic else None
        # 麦克风 VU 与放歌**共用同一对快起慢落参数**（--render-attack/--render-release）：
        # 只改一个旋钮，两条灯带的电平手感永远一致，不会一边快一边慢。
        self.level = (MicLevel(mic_full_peak, MIC_NOISE_FLOOR,
                               render_attack_tau, render_release_tau)
                      if mic else None)
        # 放歌时读系统输出峰值：与麦克风完全独立，--no-mic 也照常可用
        self.render_meter = MicLevelMeter(0, 0)
        self.render_level = MicLevel(render_full_peak, RENDER_NOISE_FLOOR,
                                     render_attack_tau, render_release_tau)
        self.mic_reverse = bool(mic_reverse)
        self._raw_frame = False      # 电平表按最终 PWM 直出；其它灯效走 gamma
        self._bright_value = None    # 放歌亮度系数的慢平滑状态（防止低亮度整数台阶闪）
        self.state = "media"
        self._media_off_since = None        # 音乐断了多久（缓冲计时）
        self.current = [(0, 0, 0)] * LED_COUNT
        # 开机静默期到期时刻（0 = 不启用）。自启时由 main() 传 BOOT_QUIET_SEC，
        # 期间不管什么状态、什么电平都强制全灭，挡住登录音/通知音误触发。
        self._boot_quiet_until = (time.time() + max(0.0, boot_quiet)
                                  if boot_quiet > 0 else 0.0)
        self._ambient_since = None          # ambient：电平连续超门限的起点
        self._stop = threading.Event()
        self.stop_event = self._stop        # 重连退避时用来中断等待

        # 媒体解码要几十 ms，放后台线程，别卡住渲染循环
        threading.Thread(target=self._media_loop, daemon=True).start()

    def _media_loop(self):
        # run_forever 内部是常驻 asyncio 循环：SMTC 的 media_properties_changed
        # 事件回调能即时触发（切歌不用等轮询），另有 0.5s 轮询兜底
        if self.media.available:
            self.media.run_forever(self._stop)

    def stop(self):
        self._stop.set()

    def _media_on(self):
        return bool(self.media.available
                    and self.media.playing and self.media.color)

    def _sound_brightness(self, lv):
        """放歌 / 环境彩虹共用的亮度系数：render_brightness 曲线 + 120ms 低通。

        亮度是慢变量，别跟着瞬态峰值每帧跳（低亮度时 int 截断会变成闪烁）；
        颗数仍由调用方用原始 lv 算，快起慢落和 60 级精度一点不动。
        两态共用同一个 _bright_value，切换状态时亮度也不会突然跳一下。
        """
        target = render_brightness(lv)
        prev = getattr(self, "_bright_value", None)
        if prev is None:
            self._bright_value = target
        else:
            kb = 1.0 - math.exp(-FRAME_INTERVAL / RENDER_BRIGHT_TAU)
            self._bright_value = prev + (target - prev) * kb
        return self._bright_value

    def compute_target(self):
        now = time.time()
        # 不管当前是哪一态都持续轮询：从 media 切回来时判定与电平都得是现成的
        if self.mic:
            self.mic.poll(now)
        if self.meter:
            self.level.update(self.meter.read(), now)
        if self.render_meter and self.render_meter.available:
            self.render_level.update(self.render_meter.read(), now)

        # 优先级：麦克风 VU > 放歌封面 > 环境彩虹 > 全灭。
        # 麦克风被占用 = 正在通话 / 录音 / 开麦，属于「状态提示」；封面配色只是
        # 氛围灯。提示压过氛围，放歌时同时开麦（直播 / K 歌 / 游戏语音）也要
        # 让电平表顶上来 —— 旧逻辑把麦克风限定在「没播音乐时」，恰好漏了这类场景。
        # 代价：Discord / 会议软件 / 浏览器常驻占麦会让封面灯效长期不出现；
        # 遇到放歌不显示封面，先跑 --diagnose 看是谁占着麦克风。
        if self.mic and self.mic.available and self.mic.in_use:
            new_state = "mic"              # 最高优先级，绕过 media 的 1.5s 缓冲
        elif self._media_on():
            self._media_off_since = None
            new_state = "media"
        else:
            if self._media_off_since is None:
                self._media_off_since = now
            stay = (self.state == "media"
                    and (now - self._media_off_since) < MEDIA_FALLBACK_DELAY)
            if stay:
                new_state = "media"
            elif self.render_meter and self.render_meter.available:
                # 没有 SMTC 曲目、麦克风也没占用：交给环境彩虹。
                # 状态本身不随「有没有声音」切换（帧内用慢落后的 value 判静音），
                # 否则声音断续会让状态切换脉冲一直闪。
                new_state = "ambient"
            else:
                # 麦克风可用但没占用：仍走 mic 态（mic_leds(False) 全灭 + 板载灭）
                new_state = "mic" if (self.mic and self.mic.available) else "idle"
        self.state = new_state
        self._raw_frame = False

        if self.state == "mic":
            busy = self.mic.in_use
            if busy:
                # 电平接口挂了就退回二值指示：亮满 8 颗 + 80% 亮度，仍看得出「在用」
                lv = self.level.value if (self.meter and self.meter.available) else 1.0
                self._raw_frame = True       # mic_leds 已按最终 PWM 算好亮度，别再过 gamma
                return mic_leds(True, lv, self.mic_reverse)
            # 没被占用：灯带全灭；板载 LED 也熄灭，完全静默（见 _status_led_tick）
            return mic_leds(False)

        if self.state == "ambient":
            # 环境彩虹 = 把放歌那套声音驱动帧的「封面色」换成固定 300° 彩虹色。
            # 默认全灭；颗数/渐入/亮度曲线/快起慢落/颜色平滑全部与放歌一致。
            # 差别只有两处：① 彩虹基色是 v=1.0 的 PWM 域纯 HSV，不过 gamma
            # 也不需要 with_glow；② 静音用慢落后的 value 判定而不是瞬时 peak，
            # 游戏音效断续时不会硬切全灭。
            self._raw_frame = True        # 最终 PWM 占空比直出，不过 gamma
            lv = self.render_level.value
            # 即使这一帧判全灭也要推进亮度低通：否则声音回来时 _bright_value
            # 还停在上一次的高值，第一颗灯会先亮一下再暗下去。
            bright = self._sound_brightness(lv) * AMBIENT_BRIGHT_GAIN
            # 静音 -> 有声的去抖：端点刚枚举、系统零碎提示音会冒出一两帧峰值，
            # 不该让第一颗灯凭空亮起来。声音一断立刻清计时，下次重新计时。
            if lv < RENDER_SILENCE_GATE:
                self._ambient_since = None
                return [(0, 0, 0)] * LED_COUNT
            if self._ambient_since is None:
                self._ambient_since = now
            if (now - self._ambient_since) < AMBIENT_ON_DELAY:
                return [(0, 0, 0)] * LED_COUNT
            n = render_led_count(lv)
            whole, extra, frac = vu_steps(n)
            base = ambient_base()
            out = [(0, 0, 0)] * LED_COUNT
            for i, idx in enumerate(mic_order(self.mic_reverse)):
                if i >= whole + extra:
                    break
                fade = frac if (i == whole) else 1.0
                out[idx] = scale(base[idx], bright * fade)
            return out

        if self.state == "media" and self.media.color:
            base = self._cover_base()
            if not (self.render_meter and self.render_meter.available):
                # 降级：这台机器的输出端点读不到峰值，回到原来的整条封面呼吸
                phase = (now % self.breathe_period) / self.breathe_period
                wave = 0.5 - 0.5 * math.cos(2 * math.pi * phase)
                level = (1.0 - self.breathe_depth) + self.breathe_depth * wave
                return [scale(c, level) for c in base]

            # 声音驱动：颜色仍是这 60 颗封面渐变色，亮几颗 / 多亮交给系统输出峰值。
            # 封面色先逐通道过 gamma 转成 PWM 域 —— 这一步不能省：
            # 直接拿感知 RGB 乘系数再 raw 直出会过曝泛白（亮暗通道一起被抬起来）。
            # 过完 gamma，白色封面满档 255/255，再由固件 setBrightness(128)
            # 限到实际 50% 占空比 —— host 端不再做第二道亮度打折。
            lv = self.render_level.value
            self._raw_frame = True          # current 是 PWM 域，静音那帧也不能再过一次 gamma
            # 亮度是慢变量：单独低通，别跟着瞬态峰值每帧跳（见 RENDER_BRIGHT_TAU）。
            # 颗数仍用原始 lv，快起慢落与 60 级精度不受影响。
            # 与环境彩虹共用 _sound_brightness()，两态曲线、平滑完全同口径。
            bright = self._sound_brightness(lv)
            # 真静音：数字输出精确为 0（没有底噪），一颗都不亮。
            # 刚过门限的极小声仍走下面的 1% 起步，两者不冲突；靠颜色平滑柔和淡出。
            if self.render_level.peak < RENDER_SILENCE_GATE:
                return [(0, 0, 0)] * LED_COUNT
            gamma_base = [apply_gamma(c) for c in base]
            n = render_led_count(lv)   # 低段压慢的幂曲线，与面板显示同一个数
            # 保底强度随亮度缩放：静音侧约 1/255、满档 18/255，全程连续，
            # 既不会让深色封面锁在同一个亮度，也不会「补了还是看不见」。
            glow_level = RENDER_MIN_GLOW * bright / RENDER_BRIGHT_MAX
            out = [(0, 0, 0)] * LED_COUNT
            # 严格 60 级：whole 颗满亮 + 第 whole 颗按 frac 渐入，无迟滞、
            # 无「最后一颗单独延后」（那条 8 颗时代的补丁会让第 60 颗几乎不出现）。
            whole, extra, frac = vu_steps(n)
            for i, idx in enumerate(mic_order(self.mic_reverse)):
                if i >= whole + extra:
                    break
                fade = frac if (i == whole) else 1.0
                raw = scale(gamma_base[idx], bright * fade)
                # 中暗/极暗封面色乘完亮度只剩几个 /255，补到最低可见亮度。
                # 保底按**感知域** base[idx] 的色相比例来（不是 gamma_base）：
                # 用 PWM 域比例会把近中性的暗蓝灰补成纯蓝，见 with_glow 的说明。
                floor = max(1, round(glow_level * fade))
                out[idx] = with_glow(raw, base[idx], floor)
            return out

        return [(0, 0, 0)] * LED_COUNT

    def _cover_base(self):
        """灯珠基色：spatial=封面从左到右的连续渐变（灯带左右对应封面左右），
        weight=按配色权重把主色当色标插值成连续渐变。两条路径最后都过一遍
        去黑回填（用左右邻居插值），保证 60 颗里没有「采样到黑色、实际不发光」
        的灯珠，也不会在渐变上凭空插进一个跳变。"""
        if self.cover_layout == "spatial" and self.media.columns:
            base = list(self.media.columns[:LED_COUNT])
            while len(base) < LED_COUNT:
                base.append(base[-1])
        else:
            base = palette_to_leds(self.media.palette)
        return fill_dark_leds(base)

    def tick(self, strip: LedStrip):
        target = self.compute_target()
        now = time.time()
        self.mode.state = self.state
        # 外部直接编辑 idle_state.json 也能生效；0.5s 查一次 mtime，别每帧做 IO
        if now - self._mode_polled >= 0.5:
            self.mode.poll()
            self._mode_polled = now
        mode = self.mode.current
        decor_on = False

        # off：整条永远不亮，覆盖一切状态
        if mode == "off":
            self.current = [(0, 0, 0)] * LED_COUNT
            target = self.current
            self._raw_frame = True
        # 装饰模式：**强制覆盖一切**，永远按所选灯效亮 —— 不管放歌 / 麦克风 /
        # 游戏 / 开机静默期，都不让位。compute_target() 照常跑（状态机、面板
        # 状态、电平采样都不受影响），只是输出帧被整个换掉；12ms 颜色平滑
        # 让切模式时自然渐变过去，不硬切。
        elif mode in DECOR_MODES:
            # 所有装饰模式都取 (基色, 强度)：强度对所有 10 种通用、默认 50%，
            # 基色只对支持自定义颜色的 6 种生效（idle_frame 里会按模式过滤）。
            # 颜色只定色相，亮度仍由模式自己的 lv 决定，两者在 _idle_tone 解耦。
            base, level = self.mode.color_of(mode)
            target = idle_frame(mode, now, base=base, level=level)
            self._raw_frame = True
            decor_on = True
        # auto：完全保持原有灯效逻辑（放歌封面 / 麦克风 VU / 环境彩虹）。
        # 开机静默期只在 auto 下生效：状态机照常跑，但灯带强制全灭。
        # current 也直接清零 —— 只把 target 清零的话，150ms 平滑会把上一帧的
        # 颜色慢慢淡出来，静默期就变成「缓缓熄灭」而不是「一直没亮过」。
        elif self._boot_quiet_until and now < self._boot_quiet_until:
            self.current = [(0, 0, 0)] * LED_COUNT
            target = self.current
            self._raw_frame = True
        # 声音驱动的三种态（录音 VU / 放歌封面灯 / 环境彩虹）都要跟得上波形：
        # 0.15s 会削平。装饰动画也走 12ms，否则颜色流动会被 150ms 平滑糊掉。
        sound_driven = ((self.state == "mic" and self.mic and self.mic.in_use)
                        or (self.state == "media" and self.render_meter
                            and self.render_meter.available)
                        or self.state == "ambient" or decor_on)
        tau = MIC_SMOOTH_TAU if sound_driven else SMOOTH_TAU
        k = 1.0 - math.exp(-FRAME_INTERVAL / tau)
        self.current = [lerp_rgb(c, t, k) for c, t in zip(self.current, target)]
        strip.set_all(self.current, raw=self._raw_frame)
        # 给面板的「自动」卡片供实时预览：10Hz 采样一次就够，别每帧做算术。
        # 面板另有 150ms 轮询，两边频率对得上。
        if now - self._live_at >= 0.1:
            self.mode.live = sample_frame(self.current)
            self._live_at = now
        # 只有一条 60 颗灯带，主循环直接写串口。
        # 板载 LED 只在事件瞬间发一条脉冲，不参与渲染帧
        if self.status_led:
            self._status_led_tick(strip)

    # ---------- 板载 LED：常驻状态 + 只在「变化」时出声 ----------

    def _track_key(self):
        """当前曲目的标识。标题拿不到就不算数，免得解码空窗被误判成切歌"""
        m = self.media
        if not (m and m.available and m.title):
            return None
        return (m.title, m.artist or "")

    def _status_led_tick(self, strip: LedStrip):
        """板载 LED = 麦克风占用的常驻状态 + 事件脉冲。

        常驻状态每帧算一次，靠 set_status_led 的缓存去重（值不变一个字节都不发）：
          麦克风在用   -> 常亮（STATUS_LED_ON）
          麦克风没在用 -> 静默熄灭（STATUS_LED_OFF），不做任何闪烁
        事件脉冲走 0x08，固件里 pulse 优先于常驻灯态，闪完自动回到常亮或熄灭：
          闪 2 下 = 切歌（SMTC 标题变了，不代表封面已到）
          闪 3 下 = 灯效状态切换
          闪 1 下 = 封面真正就绪（MD5 变化、取色更新完成），且明显滞后于切歌
        电平档位变化不发脉冲，否则会频闪。
        （主机失联的温柔呼吸仍由固件在 3 秒无数据后自己接管。）
        """
        now = time.time()
        track = self._track_key()
        cover = (self.media.cover_updates
                 if (self.media and self.media.available) else 0)

        # 1) 常驻状态：只表达「麦克风有没有被占用」，与放不放歌无关
        if self.mic is not None and self.mic.in_use:
            strip.set_status_led(STATUS_LED_ON)
            self._status_note = "常亮 · 麦克风在用"
        else:
            strip.set_status_led(STATUS_LED_OFF)
            self._status_note = "灭 · 待机静默"

        # 2) 事件脉冲（每帧最多一条：固件收到第二条 0x08 会覆盖第一条）
        times, note = 0, ""
        if self._prev_state is not None:          # None = 程序刚起来，先只记基线不闪
            if self.state != self._prev_state:
                times, note = PULSE_STATE, f"闪 {PULSE_STATE} · 状态切换"
            elif track and self._prev_track and track != self._prev_track:
                times, note = PULSE_TRACK, f"闪 {PULSE_TRACK} · 切歌"
                self._last_track_change_at = now
            elif (cover != self._prev_cover_updates
                  and now - self._last_track_change_at >= PULSE_GUARD):
                # 封面明显滞后于标题（网易云常见）：这时才需要单独报「取到了」。
                # 快速切歌时上面的 2 下已覆盖，不补闪，避免两条 0x08 互相覆盖。
                times, note = PULSE_COVER, f"闪 {PULSE_COVER} · 封面就绪"

        self._prev_state = self.state
        self._prev_track = track
        self._prev_cover_updates = cover

        if times and now >= self._pulse_guard_until:
            strip.pulse(times)
            self._pulse_guard_until = now + PULSE_GUARD
            self._note, self._note_until = note, now + NOTE_HOLD

    @property
    def status_led_note(self):
        """面板那一行：事件刚发生过就念事件，否则念当前常驻状态"""
        if time.time() < self._note_until:
            return self._note
        return self._status_note


# ============================================================
# 后台运行 + 开机自启
# ============================================================
# 【为什么不做成 Windows 服务】
# 服务一律跑在 Session 0，跟桌面会话隔离。SMTC（系统媒体传输控制）是按用户会话枚举的，
# 在 Session 0 里调用它拿到的媒体会话列表恒为空 —— 灯会一直熄灭，等于白装。
# 任务计划程序（用户登录时触发）跑在用户会话里，媒体源正常，同时也有服务的三样好处：
# 开机自启、无窗口、崩溃自动重启。所以它才是这里的正解。

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "logs", "led_host.log")
PID_PATH = os.path.join(BASE_DIR, "logs", "led_host.pid")
LOG_MAX_BYTES = 1_000_000        # 日志超过 1MB 就滚成 .old，别无限长
# ★ 2026-11-09 起本目录（ESP-WS2812）是唯一维护的一份，ESP-01S-LightStrip-60 只作归档。
# 任务名同步改成 ESP-WS2812，与已删除的旧任务区分开，且与旧 8 颗脚本的任务名不冲突。
TASK_NAME = "ESP-WS2812 60颗音乐灯带"
STARTUP_VBS_NAME = "ESP-WS2812 60颗音乐灯带.vbs"
DEFAULT_WAIT_PORT = 30           # 开机自启时给 USB 枚举 / 固件启动留的秒数


def _task_description():
    """任务计划程序里「描述」那一栏写的备注 —— 短，且和实际行为一致"""
    return (
        "WeMOS D1 mini 60 颗灯带，单进程单串口，串口按固件身份自动探测，登录自启。\n"
        "麦克风在用：60 段绿->红电平表（最高优先级）；放歌：封面 60 段渐变配色；"
        "无 SMTC 且有声：环境彩虹。\n"
        "空闲模式控制面板：http://<本机IP>:51876/esp60led（12 种，含强制全灭）。\n"
        "日志：host\\logs\\led_host.log"
    )


class _Timestamped:
    """给写进日志的每一行补个时间戳（自带的 print 不带，事后不好排查）"""

    def __init__(self, stream):
        self._s = stream
        self._bol = True

    def write(self, s):
        if not s:
            return 0
        buf = []
        for line in s.splitlines(True):
            if self._bol:
                buf.append(time.strftime("[%m-%d %H:%M:%S] "))
            buf.append(line)
            self._bol = line.endswith("\n")
        self._s.write("".join(buf))
        self._s.flush()
        return len(s)

    def flush(self):
        self._s.flush()

    def isatty(self):
        return False


def setup_background():
    """后台模式：终端一个字都不输出，全部进日志文件，另外记下 pid 方便停。

    注意：**这里不写 pid**。重复实例要先能被单实例检查拦下来，确认真的是本进程
    在跑之后才写 —— 否则被拦下的那个已经把 pid 文件冲成自己的了，
    `--autostart stop` 会去杀一个已经退出的 pid。见 main 里的 _record_pid()。
    """
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".old")
    except OSError:
        pass
    f = open(LOG_PATH, "a", encoding="utf-8")
    sys.stdout = _Timestamped(f)
    sys.stderr = sys.stdout
    print(f"--- 后台启动 ---  {' '.join(sys.argv)}")


def _record_pid():
    """确认要长驻跑了才写 pid 文件（供 --autostart stop 使用）"""
    try:
        os.makedirs(os.path.dirname(PID_PATH), exist_ok=True)
        with open(PID_PATH, "w", encoding="utf-8") as pf:
            pf.write(str(os.getpid()))
    except OSError:
        pass


# ---------------- Windows 侧的小工具 ----------------

def _decode(b):
    for enc in ("utf-8", "cp936"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def _schtasks(args):
    """schtasks 中文输出是 GBK，统一解码后再看。

    被组策略 / 安全软件拉黑时连进程都起不来（subprocess 直接抛 OSError），
    这里兜住并返回非 0 —— 调用方一律按「任务没注册」降级处理，
    不能让 --autostart status/start/stop 整个崩在 traceback 上。
    """
    try:
        p = subprocess.run(["schtasks"] + args, capture_output=True)
    except OSError as e:
        return 1, "", f"schtasks 不可用：{e}"
    return p.returncode, _decode(p.stdout), _decode(p.stderr)


def _pythonw():
    """后台要用 pythonw.exe（无窗口、无控制台）；找不到就退回当前解释器"""
    exe = sys.executable or ""
    cand = (exe[:-10] + "pythonw.exe") if exe.lower().endswith("python.exe") else exe
    if cand and os.path.exists(cand):
        return cand
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return cand if os.path.exists(cand) else exe


def _startup_dir():
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return None
    d = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    return d if os.path.isdir(d) else None


def _startup_vbs_path():
    d = _startup_dir()
    return os.path.join(d, STARTUP_VBS_NAME) if d else None


def _runtime_args(args):
    """装机时把这次的参数固化进去，以后每次自启都用同一套。

    --port 只在用户显式指定时才写：默认交给 device.json 的序列号绑定，
    否则换 USB 口后固化的旧 COM 号会一直指向空端口。
    """
    parts = ["--baud", str(args.baud),
             "--brightness", str(args.brightness),
             "--max-level", f"{args.max_level:g}",
             "--cover-layout", args.cover_layout,
             "--breathe-period", f"{args.breathe_period:g}",
             "--breathe-depth", f"{args.breathe_depth:g}",
             "--mic-full-peak", f"{args.mic_full_peak:g}",
             "--render-full-peak", f"{args.render_full_peak:g}",
             "--render-attack", f"{args.render_attack_tau:g}",
             "--render-release", f"{args.render_release_tau:g}"]
    if getattr(args, "port", None):
        parts = ["--port", str(args.port)] + parts
    if args.app_filter:
        parts += ["--app-filter", str(args.app_filter)]
    if args.no_mic or args.no_cpu:
        parts += ["--no-mic"]
    if getattr(args, "mic_reverse", False):
        parts += ["--mic-reverse"]
    return parts


def _background_cmdline(args):
    wait = args.wait_port if args.wait_port > 0 else DEFAULT_WAIT_PORT
    script = os.path.abspath(__file__)
    return (f'"{script}" --background --wait-port {wait:g} '
            + " ".join(_runtime_args(args))), wait


def _elevate(args):
    """弹 UAC 用管理员身份重跑一次自己（注册计划任务需要管理员）"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        import shlex
        exe = sys.executable or "python.exe"
        cmdline = f'"{os.path.abspath(__file__)}" ' + " ".join(shlex.quote(a) for a in args)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, cmdline, BASE_DIR, 1)
        return rc > 32
    except Exception:
        return False


def _task_xml(pyw, args_line):
    esc = lambda s: (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>{os.environ.get("USERNAME", "user")}</Author>
    <Description>{esc(_task_description())}</Description>
    <URI>\\{TASK_NAME}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT20S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{esc(pyw)}</Command>
      <Arguments>{esc(args_line)}</Arguments>
      <WorkingDirectory>{esc(BASE_DIR)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _print_installed(how, task=True):
    print()
    print("已装好 —— 以后每次登录 Windows 就在后台自动启动，没有窗口。")
    print(f"  方式  ：{how}")
    if task:
        print(f"  任务名：{TASK_NAME}")
        print("          任务计划程序库里能看到，点开「描述」就知道它管哪条灯带")
        print("  触发  ：登录后 20 秒（等 USB 枚举完）")
    else:
        print(f"  启动器：{_startup_vbs_path()}")
        print("          在「启动」文件夹里，双击它也能立刻跑起来")
    print(f"  日志  ：{LOG_PATH}")
    print("  立刻跑：python led_host_60.py --autostart start")
    print("  临时停：python led_host_60.py --autostart stop")
    print("  彻底卸：python led_host_60.py --autostart remove")


def _install_startup_vbs(pyw, args_line):
    """降级方案：放一个 vbs 到「启动」文件夹。不需要管理员，但没有崩溃自动重启"""
    path = _startup_vbs_path()
    if not path:
        print("  找不到「启动」文件夹，装不了")
        return 1
    vbs = (
        "' ESP-WS2812 60颗音乐灯带 —— 开机自启启动器\r\n"
        "' 本文件由 led_host_60.py 自动生成，改参数请重新跑 --autostart install，别手改这里。\r\n"
        "'\r\n"
        "' 作用：登录 Windows 后无窗口启动 led_host_60.py，让 60 颗 WS2812B\r\n"
        "'       跟着当前播放音乐的电平与封面配色变化；音乐停 1.5 秒后熄灯。\r\n"
        "'       串口不写死：按 device.json 里绑定的芯片序列号自动找板子。\r\n"
        f"' 主脚本：{os.path.join(BASE_DIR, 'led_host_60.py')}\r\n"
        f"' 日志  ：{LOG_PATH}\r\n"
        "' 临时停：python led_host_60.py --autostart stop\r\n"
        "' 彻底卸：python led_host_60.py --autostart remove\r\n"
        "Set sh = CreateObject(\"WScript.Shell\")\r\n"
        f"sh.CurrentDirectory = \"{BASE_DIR}\"\r\n"
        # VBScript 里两个双引号才表示一个字面引号，两段之间要用 & 拼
        "sh.Run \"\"\"" + pyw + "\"\"\" & \" " \
        + args_line.replace('"', '""') + "\", 0, False\r\n"
    )
    with open(path, "w", encoding="utf-16") as f:
        f.write(vbs)
    _print_installed("启动文件夹（不需要管理员，但崩溃不会自动重启）", task=False)
    return 0


def _remove_startup_vbs():
    path = _startup_vbs_path()
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def autostart_install(args):
    pyw = _pythonw()
    args_line, wait = _background_cmdline(args)
    print("安装开机自启…")
    print(f"  启动命令：{pyw} {args_line}")

    if args.method == "startup":
        return _install_startup_vbs(pyw, args_line)

    import tempfile
    xml_path = os.path.join(tempfile.gettempdir(), "esp_ws2812_task.xml")
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(_task_xml(pyw, args_line))

    rc, out, err = _schtasks(["/create", "/tn", TASK_NAME, "/xml", xml_path, "/f"])
    if rc == 0:
        _remove_startup_vbs()
        _print_installed("任务计划程序（登录触发，崩溃会自动重启）")
        return 0

    msg = (err or out).strip().splitlines()
    print(f"  注册失败：{msg[-1] if msg else '未知错误'}")
    if args.elevated or "拒绝访问" not in (err + out):
        # 已经是管理员还失败，或者不是权限问题 —— 换免管理员的方案
        return _install_startup_vbs(pyw, args_line)

    print("  当前窗口不是管理员，弹 UAC 提权……（弹窗里点「是」）")
    up = ["--autostart", "install", "--elevated", "--wait-port", f"{wait:g}"] + _runtime_args(args)
    if not _elevate(up):
        print("  提权没成功，改用「启动文件夹」方案（不需要管理员）")
        return _install_startup_vbs(pyw, args_line)

    for _ in range(60):                       # 等管理员那边装完
        time.sleep(1)
        rc2, _, _ = _schtasks(["/query", "/tn", TASK_NAME])
        if rc2 == 0:
            _remove_startup_vbs()
            _print_installed("任务计划程序（登录触发，崩溃会自动重启）")
            return 0
    print("  等了 60 秒也没看到任务注册成功，多半是 UAC 弹窗被取消了。")
    print("  看现状：python led_host_60.py --autostart status")
    print("  或者用不需要管理员的方案：python led_host_60.py --autostart install --method startup")
    return 1


def _read_pid():
    try:
        with open(PID_PATH, encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _pid_of_panel_owner(port=None):
    """谁在监听面板端口 —— pid 文件过期时的兜底。

    pid 文件只在「确实长驻起来」的那一刻写一次，进程被任务管理器强杀、
    或者本机曾经起过两个实例时，里面记的可能是个早已退出的 pid。
    这时按端口反查，才是真正在跑的那个。

    port 默认值在函数体里取 PANEL_PORT：这个函数定义在常量之前的位置，
    写成默认参数会在 import 阶段就抛 NameError。
    """
    port = PANEL_PORT if port is None else port
    try:
        p = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True)
        out = _decode(p.stdout)
    except OSError:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, state = parts[1], parts[3].upper()
        if state == "LISTENING" and local.endswith(f":{port}"):
            try:
                return int(parts[4])
            except ValueError:
                continue
    return None


def _pid_alive(pid):
    p = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True)
    return str(pid) in _decode(p.stdout)


def autostart_status():
    rc, out, err = _schtasks(["/query", "/tn", TASK_NAME, "/fo", "list", "/v"])
    if rc == 0:
        keys = ("任务名", "状态", "下次运行时间", "上次运行时间", "上次结果", "作者")
        for line in out.splitlines():
            if any(k in line for k in keys):
                print("  " + line.strip())
    else:
        print("  任务计划程序：未注册")

    vbs = _startup_vbs_path()
    print(f"  启动文件夹方案：{'已装 ' + vbs if vbs and os.path.exists(vbs) else '未装'}")

    pid = _read_pid()
    if not (pid and _pid_alive(pid)):
        pid = _pid_of_panel_owner(PANEL_PORT)   # pid 文件过期就按端口反查
    if pid and _pid_alive(pid):
        print(f"  后台进程：正在运行（pid {pid}）")
    else:
        print("  后台进程：没在跑")
    print(f"  日志：{LOG_PATH if os.path.exists(LOG_PATH) else '（还没有日志）'}")
    return 0


def autostart_stop():
    _schtasks(["/end", "/tn", TASK_NAME])     # 先结束任务实例，否则会被「失败重启」策略拉回来
    pid = _read_pid()
    if not (pid and _pid_alive(pid)):
        # pid 文件可能记的是被强杀过的旧进程：按面板端口反查真正在跑的那个
        pid = _pid_of_panel_owner(PANEL_PORT)
    if pid and _pid_alive(pid):
        subprocess.run(["taskkill", "/pid", str(pid), "/f"], capture_output=True)
        print(f"  已停止后台进程（pid {pid}），灯已熄。")
    else:
        print("  后台进程没在跑。")
    try:
        if os.path.exists(PID_PATH):
            os.remove(PID_PATH)
    except OSError:
        pass
    return 0


def autostart_start():
    # 已经在跑就别再起一个：两个实例会抢串口，先连上的那个会一直被踢下线
    if _panel_is_ours(PANEL_PORT):
        print("  已经在运行（面板端口有响应），不用重复启动。"
              "要重启先 --autostart stop。")
        return 0
    rc, out, err = _schtasks(["/run", "/tn", TASK_NAME])
    if rc == 0:
        print("  已让计划任务立刻启动一次（几秒后看 --autostart status 确认）。")
        return 0
    print("  计划任务没注册，直接后台启动一次：")
    pyw = _pythonw()
    argv = [pyw, os.path.abspath(__file__), "--background",
            "--wait-port", f"{DEFAULT_WAIT_PORT:g}"]
    # 被作业对象（job）管着的环境里，普通子进程会随调用方退出一起被回收 ——
    # 先试「脱离作业对象」标志；不允许（WinError 5）就退回普通方式。
    base_flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0   # DETACHED|NEW_GROUP
    try:
        subprocess.Popen(argv, cwd=BASE_DIR, close_fds=True,
                         creationflags=base_flags | 0x01000000)     # BREAKAWAY_FROM_JOB
    except OSError:
        subprocess.Popen(argv, cwd=BASE_DIR, close_fds=True,
                         creationflags=base_flags)
    print("  已启动。要开机也自动跑，先跑 --autostart install。")
    return 0


def autostart_remove():
    autostart_stop()
    rc, out, err = _schtasks(["/delete", "/tn", TASK_NAME, "/f"])
    print(f"  计划任务：{'已删除' if rc == 0 else '本来就没注册'}")
    _remove_startup_vbs()
    print("  启动文件夹：已清理")
    print("\n自启已卸掉。灯现在是灭的，想再手动跑就 python led_host_60.py。")
    return 0


def autostart_dispatch(args):
    if args.autostart == "install":
        return autostart_install(args)
    if args.autostart == "remove":
        return autostart_remove()
    if args.autostart == "status":
        return autostart_status()
    if args.autostart == "start":
        return autostart_start()
    return autostart_stop()


# ============================================================
# 自检 / 体检 / 入口
# ============================================================
def connect(port, baud, wait=0.0, max_level=MAX_LEVEL, ctl=None,
            profile=None, ask=True, log=print):
    """找到并连上「要控制的那一台」灯带。

    顺序：扫描全部串口 → 决策（绑定序列号 / 唯一候选 / 询问）→ 打开 → 再握手确认。
      - profile 里有序列号：只认这一台，端口漂移按序列号重新定位；
      - 没有绑定且只有一台候选：自动记住它（首次运行无感）；
      - 没有绑定且多台候选：ask=True 且前台有控制台时问一句选哪台；
        后台（pythonw 无 stdin）不问，暂用第一台、不写绑定；
      - 绑定的那台不在场：不接管别的板子，抛 LinkLost 让上层每 3s 重试。

    port 只是「临时首选」，不参与身份判断；wait>0 时按 1s 轮询直到超时。
    """
    profile = dict(profile or {})
    deadline = time.time() + max(0.0, wait)
    attempt = 0
    asked = False
    note = "系统没有枚举到任何串口"

    while True:
        attempt += 1
        probes = probe_devices(baud, preferred=port, max_level=max_level)
        # 只问一次：后面每 3s 的重试不再骚扰；后台模式（无 stdin）直接不问
        can_ask = (ask and not asked
                   and sys.stdin is not None and sys.stdin.isatty())
        dev, action, note = choose_device(probes, profile, ask=can_ask, log=log)
        if can_ask:
            asked = True

        if dev:
            if action in ("single", "picked") and dev.get("serial"):
                save_device_profile(dev, dev["port"])
                profile = load_device_profile()
                if action == "single":
                    log(f"  已记住这台灯带：序列号 {dev['serial']}"
                        "（写入 device.json，以后换 USB 口也能认出来）")
                else:
                    log(f"  已绑定：序列号 {dev['serial']} @ {dev['port']}")
            elif action == "fallback":
                log(f"  [提示] {note}")

            try:
                strip = LedStrip(dev["port"], baud, max_level,
                                 expect_serial=(dev.get("serial") or None))
            except Exception as e:
                note = f"{dev['port']}: 打开失败 {type(e).__name__}: {e}"
                dev = None
            else:
                # 探测到打开之间可能被拔线 / 被别的程序抢走，再确认一次身份
                if strip.handshake():
                    # 换 USB 口后 COM 号变了：把新端口记回档案（端口只是缓存）
                    note_device_port(strip.device, strip.port_name)
                    return strip
                strip.close()
                note = f"{dev['port']}: 打开后二次握手/身份校验不通过"

        if ctl:
            ctl.link_retry(str(port or "auto"), note, attempt, 3, note)
        if time.time() >= deadline:
            raise LinkLost(note or "没有找到可控制的灯带")
        if attempt == 1 or attempt % 5 == 0:
            log(f"  未找到灯带（{note}），继续探测…")
        time.sleep(1.0)


def cmd_list_devices():
    """--list-devices：把每个串口的探测结果 + 当前绑定打印成人能看懂的表。"""
    prof = load_device_profile()
    print("扫描串口并握手识别固件身份（每个口约 0.3s，请稍等）…\n")
    probes = probe_devices()
    if not probes:
        print("  没有枚举到任何串口。检查 USB 线 / CH340 驱动（ch340-fix.ps1）。")
        return 1
    for p in probes:
        desc = f"   {p['description']}" if p.get("description") else ""
        if p.get("ok"):
            mark = ""
            if prof.get("serial") and prof["serial"] == p.get("serial"):
                mark = "   ← 当前绑定"
            print(f"  {p['port']:<8} 可控制   {device_text(p, with_port=False)}{desc}{mark}")
        else:
            print(f"  {p['port']:<8} 非本设备  {p['reason']}{desc}")
    good = [p for p in probes if p.get("ok")]
    print()
    if prof:
        when = f"（绑定于 {prof['bound_at']}）" if prof.get("bound_at") else ""
        print(f"当前绑定：序列号 {prof['serial']} @ {prof.get('port') or '?'}{when}")
        if not any(prof["serial"] == p.get("serial") for p in good):
            print("  [!] 绑定的那台不在场 —— 灯带不会连，也不会去控制别的板子。")
            print("      插回原板，或 --select-device 换一台。")
    elif good:
        print("尚未绑定：下次启动时如果只有一台会自动记住，多台则会问你选哪台。")
    else:
        print("没有发现可控灯带（确认烧的是 v6 固件，且串口监视器没开着）。")
    return 0


def cmd_select_device(port_arg=""):
    """--select-device [PORT]：扫描（或只探指定口）后重新绑定一台设备。"""
    prof = load_device_profile()
    preferred = str(port_arg or "").strip()
    if preferred:
        print(f"在 {preferred} 上识别设备…\n")
        probes = probe_devices(only=preferred)
    else:
        print("扫描串口并握手识别固件身份（每个口约 0.3s，请稍等）…\n")
        probes = probe_devices()
    good = [p for p in probes if p.get("ok")]
    if not good:
        print("没有找到可控制的灯带。")
        for p in probes:
            print(f"  {p['port']:<8} {p['reason']}")
        return 1

    if len(good) == 1:
        dev = good[0]
        print(f"找到：{device_text(dev)}"
              + (f"   {dev['description']}" if dev.get("description") else ""))
    else:
        dev = _prompt_device(good)
        if dev is None:
            print("已取消，绑定未改动。")
            return 1

    if not dev.get("serial"):
        print("这块是 v5 固件，没有身份证，没法按序列号绑定；"
              "先跑 flash_d1mini.ps1 烧 v6 再来。")
        return 1
    if not save_device_profile(dev, dev["port"]):
        return 1
    msg = f"已绑定：序列号 {dev['serial']} @ {dev['port']}"
    if prof.get("serial") and prof["serial"] != dev["serial"]:
        msg += f"（原来是 {prof['serial']} @ {prof.get('port') or '?'}）"
    print(msg)
    print("写进 host/device.json；以后启动 / 重连都只认这一台，换 USB 口也不用改。")
    return 0


def cmd_forget_device():
    """--forget-device：删掉绑定，下次启动回到「扫描 + 询问」。"""
    prof = load_device_profile()
    if not prof:
        print("当前没有绑定任何设备，无需清理。")
        return 0
    if clear_device_profile():
        print(f"已清除绑定（序列号 {prof['serial']} @ {prof.get('port') or '?'}）。"
              "下次启动会重新扫描并询问。")
        return 0
    return 1


# ============================================================
# 空闲模式 + 本地控制面板（60 颗灯带）
# ============================================================
# 后台是 pythonw，没有控制台 / 窗口，热键和 stdin 都不可靠。用「配置文件 +
# 进程内 HTTP 面板」：选择写 idle_state.json（重启保持），面板线程只改内存里的
# 一个字符串属性（CPython 属性赋值原子，不用锁）。外部直接编辑文件也生效。
PANEL_SECRET = "esp60led"        # 根路径及其它路径一律 404，只有 /esp60led 可访问
PANEL_PORT = 51876               # 高位端口，避开常见服务
# 模式 + 颜色统一一个 JSON；旧的两个文件只在首次迁移时读一次
PANEL_STATE_FILE = os.path.join(BASE_DIR, "idle_state.json")
LEGACY_MODE_FILE = os.path.join(BASE_DIR, "idle_mode.txt")
LEGACY_COLOR_FILE = os.path.join(BASE_DIR, "idle_colors.json")
PANEL_HTML_FILE = os.path.join(BASE_DIR, "panel.html")

# ---- 串口链路状态：给 Web 面板显示断线 / 重连失败 ----
LINK_HINT = (
    "排查建议：\n"
    "1. 确认 USB 线插好，设备管理器里能看到 USB-SERIAL CH340 及其 COM 号；\n"
    "2. 关闭 Arduino IDE / 串口监视器等可能独占串口的程序；\n"
    "3. 灯带按「芯片序列号」认，换 USB 口后 COM 号变了也不用改任何配置；\n"
    "   同时插着好几块同型号板也只会控制绑定的那一台；\n"
    "4. 想换一台控制：python led_host_60.py --select-device（不带参数会列出并询问）；\n"
    "   只是临时指定端口：--port COM7；想看扫描结果：--list-devices；\n"
    "5. 重连是自动的（1→2→4→8…最多 30s 一次），插回后无需手动操作；\n"
    "6. 必要时在任务计划里重启「ESP-WS2812 60颗音乐灯带」服务。"
)


def _now_text():
    lt = time.localtime()
    return (f"{lt.tm_year}年{lt.tm_mon}月{lt.tm_mday}日 "
            f"{lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}")


def _available_ports():
    try:
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


# 亮度上限只在固件里做一次：v5 的 BRIGHTNESS_CAP=128（setBrightness 50% 硬限）。
# host 不再叠第二道折扣 —— 旧的 IDLE_PWM_CAP=48 先把颜色压到 48/255，
# 再乘固件 50% 只剩 24/255，既和固件「只 clamp 这一处」的约定矛盾，
# 也把呼吸 / 波浪的动态范围压得几乎看不见。装饰帧 raw 直出 0~255 全范围，
# 由固件统一限流；_idle_tone 里的 255 clamp 只是 1 字节协议约束，不是亮度限制。
IDLE_PWM_MAX = 255                # 协议上限，不再做亮度打折
FIRMWARE_BRIGHTNESS_CAP = 128     # 仅供面板显示，真正的限流在固件

IDLE_MODES = (
    ("auto",     "自动",     "放歌封面 / 麦克风电平 / 彩虹电平，空闲全灭"),
    ("off",      "全灭",     "整条强制不亮，覆盖一切"),
    ("rainbow",  "彩虹流动", "300° 渐变沿灯带缓慢流动"),
    ("breathe",  "呼吸灯",   "整条同色渐亮渐暗，可自定义颜色"),
    ("solid",    "纯色常亮", "固定色当氛围照明，可自定义颜色"),
    ("comet",    "彗星拖尾", "恒亮 10 颗循环划过，尾巴燃尽渐变"),
    ("wave",     "亮度波浪", "明暗正弦沿灯带传播，可自定义颜色"),
    ("chase",    "跑马灯",   "高饱和色块循环追逐"),
    ("fire",     "火焰",     "火苗整体起伏舔动，可自定义颜色"),
    ("aurora",   "极光",     "绿蓝缓慢流动渐变"),
    ("twinkle",  "星空",     "稀疏星点闪烁，可自定义颜色"),
    ("gradient", "静态渐变", "蓝紫双色铺满，不流动"),
)
IDLE_MODE_NAMES = tuple(k for k, _, _ in IDLE_MODES)
DECOR_MODES = tuple(k for k in IDLE_MODE_NAMES if k not in ("auto", "off"))

# 可自定义颜色的模式：卡片右上角有色点。彩虹 / 极光 / 静态渐变 / 跑马灯
# 本身是多色配色，不给色轮；但这 4 种和其余 6 种一样都有「强度」设置点。
# 彗星：本体恒亮 10 颗（头 1 + 拖尾 9），沿灯带 59→0→59 无缝循环
COMET_TAIL_LEDS = 10
COMET_STEP_SEC = 0.075         # 每颗停 75ms，60 颗一圈 4.5s

IDLE_COLOR_MODES = ("solid", "breathe", "wave", "comet", "fire", "twinkle")
# 所有装饰模式的默认整体强度：会整条全亮的模式（纯色/渐变/跑马灯/彩虹/呼吸）
# 默认只发 50%，避免 host 上限放开后一上来就吃满 1.8A。用户可在面板拖到
# 10%~100%，按模式独立保存。auto / off 不走装饰帧，不需要强度。
IDLE_DEFAULT_LEVEL = 0.5
IDLE_DEFAULT_COLORS = {
    "solid":   "#FFC896",
    "breathe": "#FFBE8C",
    "wave":    "#78B4FF",
    "comet":   "#FFDCB4",
    "fire":    "#FF5F14",
    "twinkle": "#C8DCFF",
}
CHASE_PALETTE = ((255, 40, 40), (60, 255, 80), (60, 120, 255), (255, 190, 40))


def _clamp01(v):
    return max(0.0, min(1.0, float(v)))


def _hex_to_rgb(s):
    """#RRGGBB -> (r,g,b)；纯黑没有色相，视为非法（灯会永远不亮）。"""
    s = str(s).strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        v = (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None
    return v if max(v) > 0 else None


def _idle_tone(base, lv):
    """基色(0~255 感知域) + 亮度 0~1 -> 最终 PWM，**色度与亮度解耦**。

    旧实现 _idle_pwm(base*lv) 按每颗灯的峰值归一化到 48：只要
    max(base)*lv > 48，就有 k = 48/(max(base)*lv)，乘回去 lv 被整个约掉，
    c*k 恒等于 base*48/max(base)。于是呼吸灯 4 秒里 3.2 秒都是同一个
    (48,35,26)，波浪/拖尾/火焰也全被压成一片恒亮。

    现在直接线性相乘：明暗变化 1:1 落到 0~255 全范围，而且**不放大**
    base —— 若按峰值归一化到 255，用户选的 `#101010` 会被拉成满亮白，
    自定义颜色就失去意义，前端预览也对不上。这里**不做亮度上限**：
    固件 BRIGHTNESS_CAP=128 是唯一硬限，host 再压一次就是两道相乘
    （见 .ino 的 CMD_BRIGHTNESS 注释）。
    """
    k = _clamp01(lv)
    return tuple(max(0, min(IDLE_PWM_MAX, int(round(c * k)))) for c in base)


def _hash01(i, t):
    """确定性伪随机，避免每帧 random 抖动不可控，也方便前端预览复刻"""
    v = math.sin(i * 12.9898 + t * 7.0) * 43758.5453
    return v - math.floor(v)


def idle_frame(mode, now, n=LED_COUNT, base=None, level=1.0):
    """空闲装饰帧：返回 n 颗 0~255 颜色值（调用方 raw 直出）。

    纯函数，按 now 算相位；50Hz × 60 颗的 sin/cos 开销 <1ms，不占帧预算。
    base 就是实际颜色（不放大、不改色相），lv 决定明暗，两者在
    _idle_tone 里线性相乘；level 是用户在面板上选的整体强度
    （0.1~1.0，只缩不放）。
    亮度上限由固件 BRIGHTNESS_CAP=128 统一负责，这里不再二次打折。
    auto / off / 未知模式一律全灭。
    """
    if mode not in DECOR_MODES:
        return [(0, 0, 0)] * n
    t = float(now)
    gain = _clamp01(level)
    custom = base if (mode in IDLE_COLOR_MODES and base) else None
    out = []
    for i in range(n):
        x = i / max(1, n - 1)
        lv = 1.0
        if mode == "rainbow":
            c = hsv_to_rgb((t * 40 + x * 300) % 360, 0.90, 1.0)
        elif mode == "breathe":
            c = custom or (255, 190, 140)
            # 下限压到 0.03：从近灭到满亮跨 30 倍，整个周期都看得见变化
            lv = 0.03 + 0.97 * (0.5 - 0.5 * math.cos(2 * math.pi * t / 4.0))
        elif mode == "solid":
            c = custom or (255, 200, 150)
        elif mode == "comet":
            base = custom or (255, 220, 180)
            # 用**整数颗**定位，保证任何时刻恰好 COMET_TAIL_LEDS=10 颗亮：
            #   head 沿 59→0→59 逐颗移动，k=(led_i-head)%60 是到头的环绕距离。
            # 头跑到第 0 颗后下一帧回到第 59 颗，尾巴环绕到近端，全程无缝、
            # 没有「头划出灯带后整条空掉」的空窗。
            pos = int(t / COMET_STEP_SEC) % LED_COUNT
            head = LED_COUNT - 1 - pos
            # 前端预览只有 14 颗灯珠，按比例映射回 60 颗坐标才不会显得全亮
            led_i = round(i * (LED_COUNT - 1) / max(1, n - 1))
            k = (led_i - head) % LED_COUNT
            if k < COMET_TAIL_LEDS:
                f = k / (COMET_TAIL_LEDS - 1)        # 只用于颜色渐变
                # 亮度按几何级数：头 100%、第 2 颗 50%、第 3 颗 25%、
                # 第 4 颗 12.5% …… 第 11 颗（k=10）直接归零。
                # 旧的线性 100%->30% 前几颗差别太小，看着像一片同亮。
                lv = 0.5 ** k
                # 头是所选色，尾巴「燃尽」：绿/蓝衰减比红快，越往后越暗红偏焦
                c = (int(base[0] * (1.0 - 0.55 * f)),
                     int(base[1] * (1.0 - 0.85 * f)),
                     int(base[2] * (1.0 - 0.95 * f)))
            else:
                c, lv = (0, 0, 0), 0.0
        elif mode == "wave":
            c = custom or (120, 180, 255)
            w = 0.5 + 0.5 * math.sin(2 * math.pi * (x * 2 - t * 0.35))
            lv = 0.02 + 0.98 * w ** 1.7      # 波谷近灭、波峰满亮，拉开对比
        elif mode == "chase":
            # 高饱和色块 + 短暗缝，亮度恒定在满档：低 PWM 会把色块压成灰，
            # 这就是原先「饱和度好像不对」的原因（同一个归一化 bug）。
            ph = x * 8 + t * 2
            c = CHASE_PALETTE[int(ph) % 4]
            f = ph % 1.0
            lv = 1.0 if f < 0.78 else max(0.0, (1.0 - f) / 0.22)
        elif mode == "fire":
            c = custom or (255, 96, 16)
            # 空间 + 时间都连续的多层噪声：相邻灯珠相关，才是「舔动的火苗」，
            # 不再是每颗独立随机点亮的橙色点点（旧的 _hash01(i, seed)）。
            noise = (0.50 * math.sin(x * 11 + t * 7.3)
                     + 0.30 * math.sin(x * 23 - t * 11.1 + 1.7)
                     + 0.20 * math.sin(x * 41 + t * 5.7 + 3.1))
            # 火势 / 火苗高度整体缓慢起伏（2.4s 主 + 0.9s 细），
            # 整条火苗忽高忽低 —— 这才是「火焰那种起伏」，不是恒定一片。
            height = (0.62 + 0.30 * math.sin(2 * math.pi * t / 2.4)
                      + 0.08 * math.sin(2 * math.pi * t / 0.9))
            env = max(0.0, 1.0 - x / max(0.12, height)) ** 1.4
            lv = env * (0.55 + 0.45 * (0.5 + 0.5 * noise))
        elif mode == "aurora":
            h = 120 + 80 * math.sin(x * 3 + t * 0.5)
            c = hsv_to_rgb(h % 360, 0.85, 1.0)
            w = 0.5 + 0.5 * math.sin(x * 5 - t * 0.8)
            lv = 0.04 + 0.96 * w ** 1.4
        elif mode == "twinkle":
            c = custom or (200, 220, 255)
            seed = math.floor(t * 3)
            if _hash01(i, seed * 0.31) > 0.84:
                ph = _hash01(i * 5, seed * 0.17)
                lv = 0.20 + 0.80 * abs(math.sin(t * 2.2 + ph * math.pi))
            else:
                lv = 0.0                     # 暗档严格 0：0.05 在灯上仍看得见微光
        elif mode == "gradient":
            c = tuple(int(a + (b - a) * x)
                      for a, b in zip((60, 120, 255), (255, 90, 170)))
        else:
            c, lv = (0, 0, 0), 0.0
        out.append(_idle_tone(c, lv * gain))
    return out


def sample_frame(frame, n=14):
    """把 60 颗实际输出帧按区间平均成 n 段，给面板的「自动」卡片做实时预览。

    用平均而不是取最亮，能保留渐变和「亮了几颗」的分布；面板放大后显示。
    """
    if not frame:
        return [[0, 0, 0]] * n
    out = []
    for k in range(n):
        a = k * len(frame) // n
        b = max(a + 1, (k + 1) * len(frame) // n)
        chunk = frame[a:b]
        out.append([round(sum(c[j] for c in chunk) / len(chunk)) for j in range(3)])
    return out


class ModeController:
    """模式 / 颜色 / 强度统一存**一个 JSON**，HTTP 线程写 / 主循环读，无锁。

        {"mode": "solid",
         "colors": {"solid": {"hex": "#FFC896"}},
         "levels": {"solid": 0.5, "rainbow": 0.5}}

    强度对所有 10 种装饰模式通用（不只支持自定义颜色的那 6 种），
    未单独设置的模式用 IDLE_DEFAULT_LEVEL=0.5。旧版拆成两个文件、
    level 内嵌在 colors 里，首次启动会一并迁移。
    """

    def __init__(self, path=PANEL_STATE_FILE, default="auto"):
        self.path = path
        self.current = default if default in IDLE_MODE_NAMES else "auto"
        self.state = "idle"          # 面板显示的当前灯效态
        self.live = None             # 当前实际帧的 14 段采样，供 auto 卡片实时预览
        self.colors = {}             # {mode: {"hex": "#RRGGBB"}}，只存改过的
        self.levels = {}             # {mode: 0.1~1.0}，只存改过的
        # 串口链路状态（HTTP 线程读 / 主循环写，整体替换引用，无锁）
        self.link = {"state": "up", "port": "", "error": "", "since": "",
                     "attempts": 0, "next_delay": 0, "history": [],
                     "ports": [], "device": {}, "profile": {},
                     "bound": False, "detail": LINK_HINT}
        self.panel = {"port": PANEL_PORT, "bound": False}
        self._mtime = None
        # 只有真正在跑面板状态文件时才迁移；离线探针传临时路径不碰旧文件
        if os.path.abspath(path) == os.path.abspath(PANEL_STATE_FILE):
            self._migrate()
        self._load()

    @staticmethod
    def _parse_colors(raw):
        """校验颜色表，非法项直接丢掉，不让坏数据把渲染搞崩。"""
        out = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k not in IDLE_COLOR_MODES or not isinstance(v, dict):
                    continue
                hx = str(v.get("hex", "")).strip().upper()
                if not hx.startswith("#"):
                    hx = "#" + hx
                if _hex_to_rgb(hx) is None:
                    continue
                out[k] = {"hex": hx}
        return out

    @staticmethod
    def _parse_levels(raw):
        out = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k not in DECOR_MODES:
                    continue
                try:
                    lv = float(v)
                except (TypeError, ValueError):
                    continue
                out[k] = round(max(0.1, min(1.0, lv)), 3)
        return out

    def _migrate(self):
        """旧的 txt + 扁平 JSON 合成本文件，只在第一次运行时做一次。"""
        if os.path.exists(self.path):
            return
        try:
            with open(LEGACY_MODE_FILE, "r", encoding="utf-8") as f:
                v = f.read().strip().lower()
                if v in IDLE_MODE_NAMES:
                    self.current = v
        except OSError:
            pass
        try:
            with open(LEGACY_COLOR_FILE, "r", encoding="utf-8") as f:
                old = json.load(f)
            self.colors = self._parse_colors(old)
            # 旧格式把 level 内嵌在 colors 里，搬到独立的 levels
            if isinstance(old, dict):
                self.levels = self._parse_levels(
                    {k: v.get("level") for k, v in old.items()
                     if isinstance(v, dict) and "level" in v})
        except (OSError, ValueError):
            pass
        self._write()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            # 写文件走 os.replace 原子替换，理论上读不到半截；真出错就
            # 保留内存现状，下次 poll 再读。
            print(f"[面板] 读状态文件失败：{e}")
            return
        if isinstance(data, dict):
            name = str(data.get("mode", "")).strip().lower()
            if name in IDLE_MODE_NAMES:
                self.current = name
            raw = data.get("colors")
            if raw is None:               # 兼容用户把整个文件写成扁平颜色表
                raw = {k: v for k, v in data.items()
                       if k not in ("mode", "levels")}
            self.colors = self._parse_colors(raw)
            levels = self._parse_levels(data.get("levels", {}))
            # 兼容旧文件：colors 里仍内嵌 level 时，没被 levels 覆盖的补进来
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if (isinstance(v, dict) and "level" in v
                            and k not in levels):
                        levels.update(self._parse_levels({k: v["level"]}))
            self.levels = levels
        try:
            self._mtime = os.path.getmtime(self.path)
        except OSError:
            self._mtime = None

    def poll(self):
        """外部直接编辑 idle_state.json 也能生效；主循环每 0.5s 调一次。"""
        try:
            mt = os.path.getmtime(self.path)
        except OSError:
            return
        if self._mtime is None or mt != self._mtime:
            self._mtime = mt
            self._load()

    def _write(self):
        """整体写回 + os.replace 原子替换，避免 poll 读到半截 JSON。"""
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"mode": self.current, "colors": self.colors,
                           "levels": self.levels},
                          f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            self._mtime = os.path.getmtime(self.path)
        except Exception as e:
            print(f"[面板] 写状态文件失败（本次内存里已生效）：{e}")
            try:
                os.remove(tmp)
            except OSError:
                pass

    def set(self, name):
        name = str(name).strip().lower()
        if name not in IDLE_MODE_NAMES:
            return False
        self.current = name
        self._write()
        return True

    # ---- 串口链路状态（供面板显示） ----
    def link_up(self, port, device=None):
        prof = load_device_profile()
        self.link = {"state": "up", "port": port, "error": "", "since": "",
                     "attempts": 0, "next_delay": 0, "history": [],
                     "ports": _available_ports(), "device": device or {},
                     "profile": prof, "bound": bool(prof), "detail": LINK_HINT}

    def link_retry(self, port, error, attempt, delay, note=""):
        """每次重连失败都调一次；since 只在刚断线时记，history 留最近 8 条。"""
        d = dict(self.link)
        if d.get("state") != "retry":
            d["since"] = _now_text()
            d["history"] = []
        prof = load_device_profile()
        d.update(state="retry", port=port, error=str(error),
                 attempts=attempt, next_delay=delay,
                 ports=_available_ports(), profile=prof, bound=bool(prof),
                 detail=LINK_HINT)
        hist = list(d.get("history", []))
        # note 与 error 相同时不重复记一遍，否则 history 每条都长一倍
        hist.append(f"{_now_text()} 第 {attempt} 次：{note or error}")
        d["history"] = hist[-8:]
        self.link = d

    def link_down(self, port, reason):
        d = dict(self.link)
        d.update(state="down", port=port, error=reason,
                 ports=_available_ports(), detail=LINK_HINT)
        hist = list(d.get("history", []))
        hist.append(f"{_now_text()} {reason}")
        d["history"] = hist[-8:]
        self.link = d

    def level_of(self, mode):
        """没单独设置过就用 IDLE_DEFAULT_LEVEL（默认 50%）。"""
        return self.levels.get(mode, IDLE_DEFAULT_LEVEL)

    def color_of(self, mode):
        """给 idle_frame 用的 (base_rgb, level)；强度对所有装饰模式通用。"""
        v = self.colors.get(mode)
        rgb = _hex_to_rgb(v["hex"]) if v else None
        if rgb is None:
            rgb = _hex_to_rgb(IDLE_DEFAULT_COLORS.get(mode, "#FFFFFF"))
        return rgb, self.level_of(mode)

    def set_color(self, mode, hex_value):
        mode = str(mode).strip().lower()
        if mode not in IDLE_COLOR_MODES or _hex_to_rgb(hex_value) is None:
            return False
        hx = str(hex_value).strip().upper()
        if not hx.startswith("#"):
            hx = "#" + hx
        new = dict(self.colors)
        new[mode] = {"hex": hx}
        self.colors = new                 # 整体替换，主线程永远读到完整 dict
        self._write()
        return True

    def set_level(self, mode, value):
        mode = str(mode).strip().lower()
        if mode not in DECOR_MODES:
            return False
        try:
            lv = float(value)
        except (TypeError, ValueError):
            return False
        new = dict(self.levels)
        new[mode] = round(max(0.1, min(1.0, lv)), 3)
        self.levels = new
        self._write()
        return True

    def reset_mode(self, mode):
        """恢复该模式的默认颜色 + 默认强度 50%。"""
        mode = str(mode).strip().lower()
        if mode not in DECOR_MODES:
            return False
        c = dict(self.colors)
        c.pop(mode, None)
        lv = dict(self.levels)
        lv.pop(mode, None)
        self.colors, self.levels = c, lv
        self._write()
        return True


def _panel_html_bytes():
    """每次请求都读文件，改 HTML 不用重启服务"""
    try:
        with open(PANEL_HTML_FILE, "r", encoding="utf-8") as f:
            return f.read().encode("utf-8")
    except Exception as e:
        return (f"<h1>panel.html 读取失败</h1><p>{e}</p>").encode("utf-8")


def _panel_commit():
    """启动时机取一次 git 短 commit 给页脚显示；取不到就退化成 dev。"""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=2,
            # pythonw 无控制台，别让 git.exe 弹黑窗口
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "dev"


def _panel_updated():
    """页脚的「最后修改时间」：取面板和主脚本里较新的 mtime。

    格式按用户要求写成「x年x月x日 xx:xx」。不用 strftime 的 %-m/%-d ——
    那是 glibc 扩展，Windows 的 strftime 不支持，手动拼才跨平台。
    """
    ts = []
    for p in (PANEL_HTML_FILE, os.path.join(BASE_DIR, "led_host_60.py")):
        try:
            ts.append(os.path.getmtime(p))
        except OSError:
            pass
    if not ts:
        return "—"
    lt = time.localtime(max(ts))
    return (f"{lt.tm_year}年{lt.tm_mon}月{lt.tm_mday}日 "
            f"{lt.tm_hour:02d}:{lt.tm_min:02d}")


def _panel_is_ours(port=PANEL_PORT, timeout=1.5):
    """本机该端口上是不是已经跑着一个 led_host_60.py。

    能拿到 /api/status 且字段对得上就算「自己人」；连不上、超时、返回别的东西
    一律 False（端口被别的程序占、或旧进程刚退出的空窗期），调用方继续重试即可。
    本机请求绕过系统代理 —— 以前踩过 urllib 把 127.0.0.1 也交给代理导致误判。
    """
    import urllib.request
    url = f"http://127.0.0.1:{port}/{PANEL_SECRET}/api/status"
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with op.open(url, timeout=timeout) as r:
            if r.status != 200:
                return False
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return False
    return isinstance(data, dict) and "link" in data and "modes" in data


def start_panel(controller, port=PANEL_PORT, log=print):
    """进程内 HTTP 面板，绑 0.0.0.0 供局域网访问。

    鉴权按用户要求做轻：只有 /esp60led 及其子路径可访问，根路径和任何
    其它路径一律 404。不是密码，别把它暴露到公网。
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    prefix = "/" + PANEL_SECRET
    panel_commit = _panel_commit()

    class Handler(BaseHTTPRequestHandler):
        server_version = "esp60led"

        def log_message(self, fmt, *args):
            pass                     # 后台别刷访问日志

        def _send(self, code, body, ctype="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _404(self):
            self._send(404, b"404 Not Found")

        def do_GET(self):
            u = urlparse(self.path)
            p = u.path.rstrip("/") or "/"
            if p != prefix and not p.startswith(prefix + "/"):
                return self._404()
            if p == prefix:
                return self._send(200, _panel_html_bytes(), "text/html; charset=utf-8")
            if p == prefix + "/api/status":
                data = json.dumps({
                    "mode": controller.current,
                    "state": controller.state,
                    "modes": [{"key": k, "label": l, "desc": d}
                              for k, l, d in IDLE_MODES],
                    "cap": FIRMWARE_BRIGHTNESS_CAP,
                    "colorModes": list(IDLE_COLOR_MODES),
                    "decorModes": list(DECOR_MODES),
                    "defaultColors": IDLE_DEFAULT_COLORS,
                    "colors": controller.colors,
                    "levels": controller.levels,
                    "defaultLevel": IDLE_DEFAULT_LEVEL,
                    "link": controller.link,
                    "panel": controller.panel,
                    "version": {"commit": panel_commit,
                                "updated": _panel_updated()},
                }, ensure_ascii=False).encode("utf-8")
                return self._send(200, data, "application/json; charset=utf-8")
            if p == prefix + "/api/frame":
                # 只回 14 段采样，比 status 轻得多；面板 150ms 轮询这条
                data = json.dumps({
                    "mode": controller.current,
                    "state": controller.state,
                    "live": controller.live,
                    "link": controller.link,     # 150ms 轮询，断线状态能及时反映
                }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                return self._send(200, data, "application/json; charset=utf-8")
            if p == prefix + "/api/set":
                name = (parse_qs(u.query).get("mode") or [""])[0]
                ok = controller.set(name)
                data = json.dumps({"ok": ok, "mode": controller.current},
                                  ensure_ascii=False).encode("utf-8")
                return self._send(200 if ok else 400, data,
                                  "application/json; charset=utf-8")
            if p == prefix + "/api/setcolor":
                q = parse_qs(u.query)
                mode = (q.get("mode") or [""])[0].strip().lower()
                ok = controller.set_color(mode, (q.get("hex") or [""])[0])
                data = json.dumps({"ok": ok, "mode": mode,
                                   "color": controller.colors.get(mode)},
                                  ensure_ascii=False).encode("utf-8")
                return self._send(200 if ok else 400, data,
                                  "application/json; charset=utf-8")
            if p == prefix + "/api/setlevel":
                q = parse_qs(u.query)
                mode = (q.get("mode") or [""])[0].strip().lower()
                ok = controller.set_level(mode, (q.get("level") or [""])[0])
                data = json.dumps({"ok": ok, "mode": mode,
                                   "level": controller.level_of(mode)},
                                  ensure_ascii=False).encode("utf-8")
                return self._send(200 if ok else 400, data,
                                  "application/json; charset=utf-8")
            if p == prefix + "/api/resetcolor":
                # 路径名沿用历史，语义已扩展为「恢复该模式的默认颜色 + 默认强度」
                mode = (parse_qs(u.query).get("mode") or [""])[0].strip().lower()
                ok = controller.reset_mode(mode)
                data = json.dumps({"ok": ok, "mode": mode,
                                   "default": IDLE_DEFAULT_COLORS.get(mode),
                                   "defaultLevel": IDLE_DEFAULT_LEVEL},
                                  ensure_ascii=False).encode("utf-8")
                return self._send(200 if ok else 400, data,
                                  "application/json; charset=utf-8")
            return self._404()

    def _bind():
        return ThreadingHTTPServer(("0.0.0.0", port), Handler)

    def _retry_bind(first_error):
        """端口被占用时不放弃：只要本进程还活着，Web 就必须能打开，
        否则连串口错误都看不到。

        但要分清「端口被别的程序占」和「已经有一个 led_host_60.py 在跑」：
        后者说明本进程是重复实例，不能死等 —— 两个实例会同时抢串口，
        先连上的那个会被踢成「一直重连中」。连续 3 次探测到自己人就退出，
        把串口和面板都留给已经在运行的那个。
        """
        log(f"[面板] 端口 {port} 暂时绑定失败（{type(first_error).__name__}: "
            f"{first_error}）；后台每 3s 重试，直到端口释放")
        others = 0
        while True:
            time.sleep(3.0)
            try:
                h = _bind()
            except Exception:
                if _panel_is_ours(port):
                    others += 1
                    if others >= 3:
                        log(f"[面板] 端口 {port} 上已有一个 led_host_60.py 在应答 —— "
                            "本进程是重复实例，退出，串口留给已在运行的那个")
                        os._exit(0)
                else:
                    others = 0
                continue
            controller.panel = {"port": port, "bound": True}
            log(f"[面板] 端口 {port} 绑定成功，Web 已可访问")
            h.serve_forever()
            return

    try:
        httpd = _bind()
    except Exception as e:
        controller.panel = {"port": port, "bound": False}
        threading.Thread(target=_retry_bind, args=(e,),
                         name="panel-http-retry", daemon=True).start()
        return None
    controller.panel = {"port": port, "bound": True}
    threading.Thread(target=httpd.serve_forever, name="panel-http", daemon=True).start()
    return httpd


def run_demo(strip: LedStrip):
    print(f"[demo] 板载 LED（GPIO2/D4）：切歌闪 {PULSE_TRACK} 下 → "
          f"封面就绪闪 {PULSE_COVER} 下 → 状态切换闪 {PULSE_STATE} 下")
    strip.pulse(PULSE_TRACK)
    time.sleep(1.0)
    strip.pulse(PULSE_COVER)
    time.sleep(1.0)
    strip.pulse(PULSE_STATE)
    time.sleep(1.4)
    print("[demo] （失联呼吸只有拔掉 USB 或杀掉本进程才会出现，这里演示不到）")

    print("[demo] 红 -> 绿 -> 蓝 -> 白，每种 1.5 秒")
    for name, color in [("红", (255, 0, 0)), ("绿", (0, 255, 0)),
                        ("蓝", (0, 0, 255)), ("白", (255, 255, 255))]:
        print(f"  {name}")
        strip.set_all([color] * LED_COUNT)
        time.sleep(1.5)

    print(f"[demo] 单灯扫描 2 轮：验证 {LED_COUNT} 颗灯珠能被独立寻址")
    for _ in range(2):
        for i in range(LED_COUNT):
            strip.set_all([(0, 200, 255) if j == i else (0, 0, 0) for j in range(LED_COUNT)])
            time.sleep(0.12)

    print("[demo] 彩虹：验证平滑渐变")
    t0 = time.time()
    while time.time() - t0 < 4.0:
        elapsed = time.time() - t0
        strip.set_all([hsv_to_rgb((elapsed * 90 + i * 45) % 360, 1.0, 1.0)
                       for i in range(LED_COUNT)])
        time.sleep(FRAME_INTERVAL)

    print("[demo] 呼吸：验证亮度变化")
    t0 = time.time()
    while time.time() - t0 < 4.0:
        level = 0.5 + 0.5 * math.sin((time.time() - t0) * 2 * math.pi * 0.5)
        strip.set_all([(int(120 * level), int(60 * level), int(255 * level))] * LED_COUNT)
        time.sleep(FRAME_INTERVAL)


def diagnose_mic(full_peak=MIC_FULL_PEAK):
    print("\n麦克风体检：占用 + 电平")
    w = MicWatcher()
    if not w.available:
        print("  占用检测不可用：非 Windows，或 winreg 打不开")
        return
    w.poll()
    print(f"  当前判定：{'在用' if w.in_use else '未使用'}"
          f"   （原始扫描 {'在用' if w.raw else '不在用'}）")
    print(f"  正在使用的应用：{', '.join(w.apps) if w.apps else '无'}")
    try:
        records = sorted(w._scan(), key=lambda r: r[1], reverse=True)[:8]
    except Exception:
        records = []
    if records:
        print("  最近访问过麦克风的应用（前 8 条）：")
        for name, start, stop in records:
            when = time.strftime("%m-%d %H:%M", time.localtime(
                start / 10_000_000 - _FILETIME_EPOCH_DELTA))
            print(f"    {when}  {'在用' if start > stop else '已结束'}  "
                  f"{_short_app_name(name)}")
    print(f"  去抖：连续在用 {MIC_ON_DELAY:g}s 才算（轮询 {MIC_POLL_INTERVAL:g}s，"
          f"最坏约 {MIC_ON_DELAY + MIC_POLL_INTERVAL:.2f}s 出灯），"
          f"连续空闲 {MIC_OFF_DELAY:g}s 才放开；超过 {MIC_STALE_HOURS:g}h 的残留记录忽略")

    m = MicLevelMeter()
    print(f"\n  电平接口：{'可用' if m.available else '不可用 ' + m.error}")
    if m.available:
        print(f"  当前设备峰值 peak = {m.read():.4f}"
              f"   （无人捕获时恒为 0，安静底噪约 0.007~0.010）")
    print(f"  固定量程：噪声门限 {MIC_NOISE_FLOOR:g} ~ 满档峰值 {full_peak:g}"
          f" / 声音门限 {MIC_SOUND_GATE:g}（低于此一颗都不亮）"
          f" / 快起 {RENDER_LEVEL_ATTACK_TAU:g}s 慢落 {RENDER_LEVEL_RELEASE_TAU:g}s")
    print("  校准：python led_host_60.py --mic-calibrate（说话 5 秒，直接给建议值）")
    print("  电平预览（近 -> 远，绿 -> 黄 -> 橙 -> 红；60 颗每 4 颗抽 1 个色块）：")
    for lv in (0.0, 0.02, 0.10, 0.30, 0.50, 0.70, 0.90, 1.0):
        cols = mic_leds(True, lv)
        print(f"    {lv:.2f} -> {mic_led_count(lv):.1f} 颗 / "
              f"{mic_brightness(lv):>3.0%}  " + "".join(bg(c, "  ") for c in cols[::4]))
    print("  待机：灯带全灭 + 板载 LED 熄灭；麦克风激活：板载 LED 常亮")
    print(f"  方向：{mic_order(False)}（近 -> 远）；加 --mic-reverse 变成 "
          f"{mic_order(True)}（远 -> 近）")


def calibrate_mic(seconds=5.0):
    """连续采样设备峰值，帮用户按自己麦克风校准 --mic-full-peak。

    GetPeakValue 只在「有应用打开了麦克风捕获流」时才有值（没人录音时恒 0），
    所以必须让用户一边说话一边跑。脚本自己绝不开捕获流 —— 那会把自己写进
    ConsentStore，让「麦克风没在使用」永远不成立。
    """
    m = MicLevelMeter()
    if not m.available:
        print(f"电平接口不可用：{m.error}")
        return
    print(f"采样 {seconds:g} 秒 —— 请用【正常音量】对着麦克风说话。")
    print("前提：先让一个应用占着麦克风（系统录音机 / 语音输入法 / 会议软件都行），"
          "否则设备峰值恒为 0。")
    t0 = time.time()
    samples = []
    while time.time() - t0 < seconds:
        samples.append(m.read())
        time.sleep(FRAME_INTERVAL)
    if not samples:
        print("采样时间太短，没有取到样本。")
        return
    n = len(samples)
    peak_max = max(samples)
    peak_avg = sum(samples) / n
    clip_ratio = sum(1 for p in samples if p >= 0.995) / n
    print(f"采样 {n} 次：最大 {peak_max:.4f} / 平均 {peak_avg:.4f}"
          f" / 顶到 1.0 的帧占 {clip_ratio:.0%}"
          f"   （当前满档量程 {MIC_FULL_PEAK:g}）")
    if peak_max <= MIC_NOISE_FLOOR * 2:
        print("没捕到声音：确认有应用正在用麦克风，然后重跑一次。")
        return
    if clip_ratio >= 0.10 or peak_max >= 0.995:
        print()
        print("[!] 检测到削波：peak 顶到 1.0，这个信号已经没有动态范围。")
        print("    --mic-full-peak 已经是物理上限 1.00，调小只会更早满档，改软件没用。")
        print("    请从信号源头降增益：")
        print("    1) 控制面板 → 声音 → 录制 → 麦克风 → 级别：把「麦克风」调低，")
        print("       「麦克风加强 / Microphone Boost」设为 0dB 或关掉；")
        print("    2) 关掉录音 / 会议 / 语音软件里的「自动增益控制 AGC」；")
        print("    3) 麦克风离嘴 15~20cm（贴嘴说话本来就容易打满）。")
        print("    调完重跑本命令，目标是正常说话 peak 落在 0.3~0.6、削波占比接近 0%。")
        return
    suggest = min(1.0, max(0.05, (peak_max - MIC_NOISE_FLOOR) / 0.55))
    print(f"想让这个音量落在约 4~5 颗：--mic-full-peak {suggest:.2f}")
    print("想让它更靠后（更不容易满档）就把值调大，上限 1.00；反之调小。")


def calibrate_render(seconds=5.0):
    """采样系统输出设备的峰值，帮用户标定 --render-full-peak。

    同样只读 meter，不开 loopback 捕获流、不碰麦克风使用记录。
    """
    m = MicLevelMeter(0, 0)
    if not m.available:
        print(f"输出端点峰值接口不可用：{m.error}")
        print("这台机器的声卡/驱动可能不支持 render meter，程序会自动降级回封面呼吸。")
        return
    print(f"采样 {seconds:g} 秒 —— 请播放一首常听的歌（音量用平时的水平）。")
    t0 = time.time()
    samples = []
    while time.time() - t0 < seconds:
        samples.append(m.read())
        time.sleep(FRAME_INTERVAL)
    if not samples:
        print("采样时间太短，没有取到样本。")
        return
    hi = max(samples)
    avg = sum(samples) / len(samples)
    print(f"采样 {len(samples)} 次：最大 {hi:.4f} / 平均 {avg:.4f}"
          f"   （当前满档 {RENDER_FULL_PEAK:g}）")
    if hi <= 0.001:
        print("没捕到播放音频：确认系统音量没静音、确实有声音在播，然后重跑一次。")
        return
    suggest = min(1.0, max(0.05, avg / 0.45))
    print(f"想让平均音量落在约 4~5 颗：--render-full-peak {suggest:.2f}")
    print("值越小灯越活跃（更容易满档），越大越保守；默认 1.00 已吃满 0~1 物理范围。")


def diagnose(watch=False, full_peak=MIC_FULL_PEAK):
    """体检数据源。watch=True 时持续刷新，用来观察切歌能否跟上"""
    while True:
        print("=" * 62)
        print("媒体源体检")
        diagnose_media()
        diagnose_mic(full_peak)
        print("\n系统输出端点体检（放歌灯效的数据源）")
        rm = MicLevelMeter(0, 0)
        print(f"  峰值接口：{'可用' if rm.available else '不可用 ' + rm.error}"
              f"   当前 peak = {rm.read():.4f}")
        print("  不可用会自动降级回整条封面呼吸；可用时放歌由输出峰值驱动")
        if not watch:
            print("\n" + "=" * 62)
            return
        print("\n[watch] 2 秒后刷新，Ctrl+C 退出")
        try:
            time.sleep(2.0)
        except KeyboardInterrupt:
            print("\n退出。")
            return


def run_monitor(strip: LedStrip, app_filter=None, cover_layout="spatial",
                ui=True, breathe_period=BREATHE_PERIOD, breathe_depth=BREATHE_DEPTH,
                mic=True, mic_reverse=False, status_led=True,
                mic_full_peak=MIC_FULL_PEAK, render_full_peak=RENDER_FULL_PEAK,
                render_attack_tau=RENDER_LEVEL_ATTACK_TAU,
                render_release_tau=RENDER_LEVEL_RELEASE_TAU,
                boot_quiet=0.0, mode=None):
    mon = Monitor(app_filter, cover_layout, breathe_period, breathe_depth,
                  mic, mic_reverse, status_led, mic_full_peak, render_full_peak,
                  render_attack_tau, render_release_tau, boot_quiet, mode)
    if boot_quiet > 0:
        print(f"[monitor] 开机静默期 {boot_quiet:g}s：期间灯带强制全灭，"
              "挡住登录音/通知音误触发；环境彩虹另需连续 "
              f"{AMBIENT_ON_DELAY:g}s 有声才起灯")
    print("[monitor] 状态优先级：麦克风 VU > 放歌封面 > 环境彩虹 > 全灭"
          "（麦克风占用时放歌也让位）")
    if mon.media.available:
        print("[monitor] 音乐封面呼吸灯")
        if mon.render_meter.available:
            print(f"          播放中且麦克风没占用 -> 封面配色 + 系统输出峰值驱动"
                  f"（{cover_layout}，满档 {render_full_peak:g}，颗数/亮度随音量）")
            print(f"          真静音 peak<{RENDER_SILENCE_GATE:g} 全灭；"
                  f"极小声从 {RENDER_BRIGHT_FLOOR:.0%} 起步")
            print(f"          电平响应 快起 {render_attack_tau*1000:.0f}ms / "
                  f"慢落 {render_release_tau*1000:.0f}ms"
                  f"（放歌 + 麦克风 VU 共用）")
        else:
            print(f"          播放中 -> 封面配色 + 呼吸（{cover_layout}，"
                  f"周期 {breathe_period:g}s，幅度 {breathe_depth:.2f}）"
                  "  [输出端点不可用，降级]")
    else:
        print("[monitor] 媒体源不可用（缺 WinRT/Pillow），只会走麦克风指示")
    if mon.mic and mon.mic.available:
        print("          麦克风占用 -> 电平表（最高优先级，同时放歌也让位）；"
              "未占用才轮到封面 / 彩虹")
        print(f"          音乐停后留 {MEDIA_FALLBACK_DELAY:g}s 缓冲防切歌闪灭，"
              "但麦克风占用会直接绕过这段缓冲")
        if mon.meter and mon.meter.available:
            print(f"          电平 {FRAME_HZ}Hz · 绿->黄->橙->红 · "
                  f"{'远 -> 近' if mic_reverse else '近 -> 远'}（--mic-reverse 可翻转）"
                  f" · 亮度 1.2%~80% · lv=1.0 才 {LED_COUNT} 颗")
            print(f"          固定量程 peak {MIC_NOISE_FLOOR:g}~{mic_full_peak:g}"
                  f"（--mic-calibrate 实测 / --mic-full-peak 校准）"
                  f" · 低于 {MIC_SOUND_GATE:g} 全灭")
    else:
        print("          麦克风检测不可用（--no-mic / 非 Windows）："
              "封面 / 环境彩虹照常，不再有电平表抢占")
    print(f"          降级呼吸走 gamma + {strip.max_level:.0%} 上限（--max-level）；"
          f"声音驱动灯效 raw 直出（放歌 {RENDER_BRIGHT_FLOOR:.0%}~"
          f"{RENDER_BRIGHT_MAX:.0%} / VU 80%），亮度上限交给固件 "
          f"{FIRMWARE_BRIGHTNESS_CAP}/255 硬限，host 不二次打折；"
          f"固件侧 --brightness {strip.brightness}")
    if status_led:
        print("          板载 LED(GPIO2/D4)：未占用=灭 / 占用=常亮；"
              f"另切歌闪 {PULSE_TRACK} 下 / 封面就绪闪 {PULSE_COVER} 下 / "
              f"状态切换闪 {PULSE_STATE} 下 / 失联温柔呼吸")
    print("          Ctrl+C 退出\n")

    dsp = Display(enabled=ui)
    fps = 0.0
    frames = 0
    fps_t0 = time.time()
    last_ui = 0.0
    last_title = None
    last_state = None
    try:
        while True:
            t0 = time.time()
            try:
                mon.tick(strip)
            except LinkLost as e:
                # 睡眠唤醒 / 拔线 / 驱动重枚举 —— 指数退避重连，活了就继续
                print(f"\n[!] 串口断开：{e}")
                print("    开始重连（1→2→4→8…最多 30s 一次），Ctrl+C 可退出")
                ctl = mon.mode
                ctl.link_retry(strip.port_name, str(e), 0, 1,
                               "串口写入失败，开始自动重连")

                def on_progress(attempt, delay, err, found,
                                _ctl=ctl, _strip=strip):
                    _ctl.link_retry(
                        _strip.port_name, err, attempt, delay,
                        ("找到 %s 但打开失败" % found) if found else "未找到串口")

                if not strip.reconnect(mon.stop_event, progress=on_progress):
                    ctl.link_down(strip.port_name, "已放弃重连（服务收到停止信号）")
                    print("    已放弃重连，退出。")
                    break
                strip.resume()
                ctl.link_up(strip.port_name, strip.device)
                # resume() 已把固件侧清空；host 侧的颜色平滑状态也要一起归零，
                # 否则下一帧会从「断链前那一帧」慢慢 lerp 回来，又淡入一颗旧灯。
                mon.current = [(0, 0, 0)] * LED_COUNT
                mon._ambient_since = None   # 重连后重新走 ambient 起灯去抖
                last_ui = 0.0          # 面板下次重绘，避免显示断线前的旧数据
                continue
            frames += 1

            if t0 - fps_t0 >= 2.0:
                fps = frames / (t0 - fps_t0)
                frames, fps_t0 = 0, t0
            if not ui:
                # 后台没有面板，切歌/状态切换各写一行日志，事后看灯为什么亮/灭全靠它
                if mon.state != last_state:
                    last_state = mon.state
                    print(f"[state] {mon.state}")
                if mon.media.available:
                    t = mon.media.title
                    if t != last_title:
                        last_title = t
                        print(f"[media] {t} — {mon.media.artist}" if t
                              else "[media] （没在播放）")
            if t0 - last_ui >= 0.5:            # 面板独立按 2Hz 重绘，跟渲染帧率解耦
                dsp.render(mon, fps)
                last_ui = t0

            time.sleep(max(0.0, FRAME_INTERVAL - (time.time() - t0)))
    finally:
        dsp.finish()                       # 先把光标移到面板下方，后续输出才不会盖住面板
        mon.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None, metavar="PORT",
                    help="临时首选串口（如 COM7）。不指定=按 device.json 里绑定的"
                         "序列号自动找；从没绑定过则扫描全部串口，只有一台会自动记住，"
                         "多台时问你要控制哪一台")
    ap.add_argument("--list-devices", action="store_true",
                    help="扫描全部串口，列出能认出的灯带（端口 + 型号 + 序列号），"
                         "并标出当前绑定的是哪一台")
    ap.add_argument("--select-device", nargs="?", const="", default=None, metavar="PORT",
                    help="重新绑定要控制的设备：不带值=扫描后列出并询问；"
                         "带 COM7=只在那一个口上认出序列号并绑定")
    ap.add_argument("--forget-device", action="store_true",
                    help="忘掉已绑定的设备（删 device.json），下次启动重新询问")
    ap.add_argument("--panel-port", type=int, default=PANEL_PORT, metavar="P",
                    help=f"控制面板端口（默认 {PANEL_PORT}，高位避冲突）；"
                         "绑 0.0.0.0 供局域网访问")
    ap.add_argument("--no-panel", action="store_true",
                    help="不启动 HTTP 控制面板，只靠 host/idle_state.json 切换模式")
    ap.add_argument("--idle-mode", default="auto", choices=list(IDLE_MODE_NAMES),
                    help="空闲模式初值（默认 auto）；idle_state.json 存在时以文件为准")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--brightness", type=int, default=DEFAULT_BRIGHTNESS,
                    help=f"固件侧全局亮度 0-255（默认 {DEFAULT_BRIGHTNESS}）；"
                         "v5 固件会硬限到 128（50%%），60 颗灯带请外接 5V >=2A")
    ap.add_argument("--max-level", type=float, default=MAX_LEVEL, metavar="X",
                    help=f"降级封面呼吸的输出上限 0~1（默认 {MAX_LEVEL:g}）。"
                         "声音驱动灯效按自己的亮度曲线直出，不受它限制")
    ap.add_argument("--no-mic", action="store_true",
                    help="关掉麦克风指示与最高优先级抢占：只按放歌 / 环境彩虹走，"
                         "板载 LED 也灭（常驻占麦的 App 压住封面时用这个）")
    ap.add_argument("--mic-reverse", action="store_true",
                    help="翻转电平条点亮方向（默认从离板子最近的灯开始）")
    ap.add_argument("--mic-full-peak", type=float, default=MIC_FULL_PEAK, metavar="X",
                    help=f"电平表满档对应的设备峰值 0~1（默认 {MIC_FULL_PEAK:g}，"
                         "已吃满物理范围）。灯几乎不亮才调小；贴嘴就满档请降低系统麦克风增益")
    # 兼容旧的自启任务命令行：老参数等价于 --no-mic，启动不会因为未知参数崩掉
    ap.add_argument("--no-cpu", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-status-led", action="store_true",
                    help="不用板载 LED(GPIO2/D4)做常亮状态指示和事件提示"
                         "（GPIO2 另有用途时才需要）")
    ap.add_argument("--app-filter", default=None,
                    help="只认某个播放器的媒体会话，例如 cloudmusic.exe")
    ap.add_argument("--cover-layout", default="spatial", choices=["spatial", "weight"],
                    help="封面取色方式：spatial 按封面从左到右采 60 颗平滑渐变"
                         "(灯带左右对应封面左右，默认) / weight 按配色权重把主色"
                         "当色标插值成渐变；两种都不会出现黑灯")
    ap.add_argument("--breathe-period", type=float, default=BREATHE_PERIOD, metavar="SEC",
                    help=f"呼吸周期秒数（默认 {BREATHE_PERIOD:g}）。越小呼吸越快")
    ap.add_argument("--breathe-depth", type=float, default=BREATHE_DEPTH, metavar="X",
                    help=f"呼吸幅度 0~1（默认 {BREATHE_DEPTH:g}）。越大明暗差别越明显，"
                         "0 = 恒亮不呼吸")
    ap.add_argument("--no-ui", action="store_true",
                    help="不画终端面板（后台模式自动生效）")
    ap.add_argument("--background", action="store_true",
                    help="后台模式：界面全关，日志写 logs/led_host.log（开机自启时自动带上）")
    ap.add_argument("--wait-port", type=float, default=0.0, metavar="SEC",
                    help="串口没就绪时最多等几秒（默认 0 不等；自启时装成 %g 秒）"
                         % DEFAULT_WAIT_PORT)
    ap.add_argument("--autostart", choices=["install", "remove", "status", "start", "stop"],
                    metavar="WHAT",
                    help="开机自启管理：install 装 / remove 卸 / status 看状态 / "
                         "start 立刻跑 / stop 临时停")
    ap.add_argument("--method", choices=["task", "startup"], default="task",
                    help="install 用的方式：task=任务计划程序（默认，需管理员一次）/"
                         "startup=启动文件夹（无需管理员）")
    ap.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS,
                    default=False)
    ap.add_argument("--demo", action="store_true", help="灯带自检，不采集任何数据")
    ap.add_argument("--diagnose", action="store_true",
                    help="体检媒体源 + 麦克风占用/电平，不点亮")
    ap.add_argument("--mic-calibrate", action="store_true",
                    help="采样 5 秒设备峰值，帮你校准 --mic-full-peak"
                         "（需先有应用占着麦克风并说话）")
    ap.add_argument("--render-full-peak", type=float, default=RENDER_FULL_PEAK,
                    metavar="X",
                    help=f"放歌时输出峰值的满档值（默认 {RENDER_FULL_PEAK:g}）。"
                         "灯太暗就调小；瞬态老冲满档可略调大于 1（如 1.2）压一压")
    ap.add_argument("--render-calibrate", action="store_true",
                    help="采样 5 秒系统播放峰值，打印最大/平均并给 --render-full-peak 建议")
    ap.add_argument("--render-attack", type=float, default=RENDER_LEVEL_ATTACK_TAU,
                    dest="render_attack_tau", metavar="SEC",
                    help=f"声音电平上升时间常数秒（默认 {RENDER_LEVEL_ATTACK_TAU:g}，"
                         "放歌+麦克风共用）。参数名沿用历史；调小更跟手、调大更稳")
    ap.add_argument("--render-release", type=float, default=RENDER_LEVEL_RELEASE_TAU,
                    dest="render_release_tau", metavar="SEC",
                    help=f"声音电平下降时间常数秒（默认 {RENDER_LEVEL_RELEASE_TAU:g}，"
                         "放歌+麦克风共用）。调大托住峰值不闪、调小灭得更快")
    ap.add_argument("--watch", action="store_true",
                    help="配合 --diagnose 持续刷新，用来观察切歌能否跟上")
    ap.add_argument("--list-ports", action="store_true")
    args = ap.parse_args()

    if args.background:
        setup_background()          # 早于一切输出：之后的 print 都进日志

    if args.autostart:
        return autostart_dispatch(args)

    if args.list_ports:
        print("当前串口：")
        for p in sorted(list_ports.comports()):
            print(f"  {p.device}   {p.description or ''}")
        return 0

    if args.list_devices:
        return cmd_list_devices()

    if args.select_device is not None:
        return cmd_select_device(args.select_device)

    if args.forget_device:
        return cmd_forget_device()

    if args.render_calibrate:
        calibrate_render()
        return 0

    if args.mic_calibrate:
        calibrate_mic()
        return 0

    if args.diagnose:
        diagnose(args.watch, args.mic_full_peak)
        return 0

    # 面板先于串口启动：板子没插 / COM 号不对时也要能在 Web 上看到错误，
    # 而不是进程直接退出、只留一个打不开的页面。
    # 面板绑 0.0.0.0；首次运行若被 Windows 防火墙拦，需在防火墙里放行 Python/该端口。
    mode = ModeController(default=args.idle_mode)
    # 单实例保护，必须早于碰串口：面板端口上已经有 led_host_60.py 在应答，
    # 说明是重复启动。放它过去会两个进程抢同一个串口，先连上的那个被踢成
    # 「一直重连中」——面板显示断开、灯却还在动，最难排查。
    if not args.no_panel and _panel_is_ours(args.panel_port):
        print(f"已有一个 led_host_60.py 在运行（面板端口 {args.panel_port} 有响应），"
              "本次启动取消。要重启请先 --autostart stop。")
        return 0
    if args.background:
        _record_pid()            # 确认没被拦下来，才占 pid 坑
    if not args.no_panel:
        panel = start_panel(mode, args.panel_port)
        if panel is not None:
            print(f"控制面板：http://<本机IP>:{args.panel_port}/{PANEL_SECRET}"
                  "　（局域网可访问；根路径与非法路径一律 404）")
    print(f"空闲模式：{mode.current}（面板或 host/idle_state.json 可改，"
          f"亮度由固件 {FIRMWARE_BRIGHTNESS_CAP}/255 硬限，host 不二次打折）")

    # 启动连接：失败不退出，每 3s 重试（面板会一直显示当前错误与重试次数），
    # 插回 USB 后自动接上并继续跑灯效。第一次用 --wait-port 等枚举。
    strip = None
    attempt = 0
    profile = load_device_profile()
    print(f"打开 {args.port or '（自动，按绑定序列号找）'} @ {args.baud} ...")
    if profile:
        print(f"绑定设备：序列号 {profile['serial']}"
              + (f"（上次在 {profile['port']}）" if profile.get("port") else "")
              + "　→ 换 USB 口也认这一台")
    else:
        print("尚未绑定设备：先扫描全部串口，只有一台会自动记住，多台会问你要哪台")
    while strip is None:
        attempt += 1
        try:
            strip = connect(args.port, args.baud,
                            args.wait_port if attempt == 1 else 0.0,
                            args.max_level, ctl=mode, profile=profile,
                            # 后台 pythonw 没有控制台，问了会卡死 —— 不问，
                            # 多台候选时暂用第一台并写进日志（面板也能看到）
                            ask=not args.background)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            print(f"打不开串口：{err}")
            print("常见原因：Arduino IDE 串口监视器没关 / 板子没插 / "
                  "绑定的那台不是当前插着的这台（--select-device 可换）")
            mode.link_retry(args.port or "auto", err, attempt, 3,
                            "启动连接失败，等待重插")
            try:
                time.sleep(3)
            except KeyboardInterrupt:
                mode.link_down(args.port or "auto", "用户中断，未连接串口")
                return 1
    mode.link_up(strip.port_name, strip.device)
    dev = strip.device or {}
    print(f"已连接 {strip.port_name} · "
          + ("v5 固件（无身份证，建议烧 v6）" if dev.get("legacy") else
             f"{dev.get('model')} v{dev.get('version')} · 序列号 {dev.get('serial')}"))

    # 开机 / 手动启动的第一条指令必须是全灭，不能是亮度帧：
    # USB 待机供电时固件不重启，pixels 里还留着关机前最后一帧颜色。
    strip.blank()
    strip.set_brightness(args.brightness)

    try:
        if args.demo:
            while True:
                run_demo(strip)
        else:
            run_monitor(strip, args.app_filter, args.cover_layout,
                        ui=not (args.no_ui or args.background),
                        breathe_period=args.breathe_period,
                        breathe_depth=args.breathe_depth,
                        mic=not (args.no_mic or args.no_cpu),
                        mic_reverse=args.mic_reverse,
                        status_led=not args.no_status_led,
                        mic_full_peak=args.mic_full_peak,
                        render_full_peak=args.render_full_peak,
                        render_attack_tau=args.render_attack_tau,
                        render_release_tau=args.render_release_tau,
                        # 只有自启命令行带 --wait-port / --background；
                        # 前台手动调试不加静默期，免得「改完看不见效果」。
                        boot_quiet=(BOOT_QUIET_SEC if (
                            args.wait_port > 0 or args.background) else 0.0),
                        mode=mode)
    except KeyboardInterrupt:
        print("\n退出，熄灯。")
    finally:
        strip.off()
        strip.close()
    return 0


if __name__ == "__main__":
    # 后台模式下没人看得见控制台，异常必须落进日志，且要用非 0 退出码
    # 告诉任务计划程序「这次挂了，按策略重启」
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n退出，熄灯。")
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
