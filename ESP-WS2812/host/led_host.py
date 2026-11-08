#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音乐封面呼吸灯（WeMOS D1 mini + 8 颗 WS2812B）—— 唯一脚本

两件事，按优先级：
  1. 有音乐在播 —— 认出系统里正在播放的音乐，把专辑封面的配色铺到 8 颗灯珠上；
     **亮几颗 / 多亮由默认输出设备的实时峰值决定**（读的是系统播放混音，
     不是麦克风），颜色仍是这 8 颗封面配色；采样到的黑色不会分给灯珠，
     改用同一张封面里的其它颜色回填。真静音（peak 约 0）一颗都不亮，
     极小声从 1% 亮度起步。输出端点读不到峰值时才降级回整条呼吸。
  2. 没在播音乐 —— 麦克风没被占用：**灯带全灭、板载 LED 也灭**，完全静默；
     正在被占用：板载 LED 常亮，音量同时决定亮几颗（1~8，从最近端往最远端）、
     颜色（绿 -> 黄 -> 橙 -> 红）和亮度（1% -> 80% 最终 PWM 占空比）；
     lv=1.0 才刚好亮满 8 颗，没声音或声音极低时一颗都不亮。

「谁在用」读 Windows 隐私同意记录（ConsentStore 下 microphone 键的
LastUsedTimeStart / LastUsedTimeStop），带去抖滤掉输入法那种几十毫秒的短脉冲；
「声音多大」分两路，都是 WASAPI 的 IAudioMeterInformation 设备峰值，
**只读 meter、不打开任何捕获流**，所以不会把自己写进注册表把判定污染成永远在用：
  - 放歌时读默认输出端点 (eRender/eConsole)：系统播放混音峰值，戴耳机也照样有值；
  - 麦克风 VU 读默认输入端点 (eCapture/eMultimedia)：需要别的应用占着麦克风。
同一份 ctypes COM 代码，只是 GetDefaultAudioEndpoint 的参数不同。零第三方依赖，渲染 100Hz。

降级路径的封面呼吸受 MAX_LEVEL = 0.70（--max-level）限制，在 gamma 之前乘到每颗灯上。
两种声音驱动灯效是例外：亮度按「最终 PWM 占空比」直出（1% 过 gamma 会全黑），
放歌先把封面色过 gamma 再乘亮度（最亮白色封面约 94/255，与旧封面呼吸一致），
VU 峰值 80%。固件侧 --brightness 默认满档，一般别动。

板载 LED（GPIO2 / D4）现在兼两职：
    常驻状态 —— 麦克风没占用 = 熄灭（待机静默）；麦克风占用 = 常亮
    事件脉冲 —— 切歌闪 2 下 / 封面就绪闪 1 下 / 状态切换闪 3 下
                （脉冲优先，闪完回到常驻状态；封面只在明显滞后于切歌时才单独报）
主机失联（关机 / 拔 USB / 后台服务崩）由固件自己判断：3 秒没数据又没收到 OFF
就转成温柔呼吸（PWM 渐亮渐暗，2.6s 一个来回）—— 那时候串口已经断了，
这台电脑发不出任何命令，只能由固件自己接管。加 --no-status-led 可整块关掉。

（曾经试过「没播音乐时跟屏幕画面走」的抓屏氛围光，因为独占全屏的游戏抓不到画面、
且 GDI 回读整屏要 16ms/次太耗资源，已经移除，不再包含在本文件里。）

用法：
    python led_host.py --list-ports              # 看串口号
    python led_host.py --diagnose                # 体检媒体源 + 麦克风占用，不点亮
    python led_host.py --demo                    # 灯带自检（红绿蓝白/扫描/彩虹/呼吸）
    python led_host.py                           # 默认：跟随媒体封面呼吸
    python led_host.py --app-filter cloudmusic.exe   # 只认网易云，别的播放器不来抢灯
    python led_host.py --cover-layout weight     # 按配色权重铺（默认 spatial 左右对应封面）

开机自启 / 后台常驻（Windows）：
    python led_host.py --autostart install       # 装好：以后一登录就自动在后台跑（会弹一次 UAC）
    python led_host.py --autostart status        # 看有没有在跑、什么时候跑的、日志在哪
    python led_host.py --autostart stop          # 临时停掉（不卸，下次登录还会起来）
    python led_host.py --autostart start         # 立刻启动一次
    python led_host.py --autostart remove        # 彻底卸掉自启

常用参数：
    --port COM4              串口号
    --max-level 0.70         封面呼吸灯珠最大亮度 0~1（默认 0.70）
    --brightness 255         固件侧二次亮度（默认满档，一般不改）
    --breathe-period 4.0     呼吸周期（秒），越小呼吸越快
    --breathe-depth 0.40     呼吸幅度 0~1，越大明暗差别越明显
    --no-mic                 关掉麦克风指示，没播音乐就熄灯
    --mic-reverse            翻转电平条点亮方向（默认从离板子最近的灯开始）
    --mic-full-peak 1.00     麦克风 VU 满档对应的输入峰值（默认吃满 0~1 量程）
    --mic-calibrate          采样 5 秒输入峰值，帮你校准 --mic-full-peak
    --render-full-peak 1.00  放歌时输出峰值满档值（灯太暗调小，太容易满档调大）
    --render-calibrate       播放一首歌采样 5 秒，给 --render-full-peak 建议
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

LED_COUNT = 8


# 九宫格位置权重：中心是画面主体，权重最高；四角最次要
GRID_WEIGHT = ((0.8, 1.1, 0.8),
               (1.1, 1.8, 1.1),
               (0.8, 1.1, 0.8))

# ---- 去黑回填：8 颗灯里不允许出现黑色 ----
# 判据放在「最终 PWM 域」而不是颜色名上：_normalize_values 会把纯黑抬成
# (38,38,38) 的灰，看着不是黑，过 gamma 却只剩 (1,1,1)，肉眼就是黑灯。
# 加饱和度条件是为了保住深蓝这类暗彩色（(20,30,60) gamma 后最大通道只有 4，
# 但 s≈0.67）—— 它有色相，配合色相保底仍看得见，不该被当成黑替换掉。
DARK_MAX_GAMMA = 8           # gamma 后最大通道低于此值才算「太暗」
DARK_MAX_SAT = 0.30          # 且饱和度低于此值才算「没有色相的黑白灰」
DARK_FALLBACK_VALUE = 0.35   # 整张封面全黑时，保留色相把明度提到这个值


def analyze_cover(img_bytes: bytes, top: int = 5):
    """
    封面 -> 带权重的多色配色。

    做法：切成 3x3 九宫格（比整图取单色准得多，能同时拿到主体色和背景色），
    每格各自量化取色，按「像素占比 × 饱和度 × 位置权重」打分；
    再按色相/明度相近原则合并同色系，累加权重；最后取 top N 并归一化。

    返回 [(rgb, weight), ...]，按权重降序，weight 之和为 1。
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
                # 免得"黑色很多的封面"一点暗部都没有；发灯前 fill_dark_leds() 会把
                # 这些黑位换成同封面其它颜色，所以灯带上不会出现黑灯。
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


def _dominant(img):
    """一张图的主色：量化成 5 簇，按「像素数 × 轻饱和加权 × 轻明度加权」挑最高的那簇。
    纯黑（v<0.02）直接丢，否则夜景/暗场会配出一片黑"""
    q = img.quantize(colors=5, method=Image.MEDIANCUT)
    palette = q.getpalette()
    best, best_score = None, -1.0
    for count, idx in q.getcolors():
        r, g, b = palette[idx * 3:idx * 3 + 3]
        _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if v < 0.02:
            continue
        score = count * (0.65 + 0.35 * s) * (0.40 + 0.60 * v)
        if score > best_score:
            best_score, best = score, (r, g, b)
    return best or (0, 0, 0)


def _columns_from_image(img, n):
    """横向切 n 条、每条取主色 —— 灯珠 i 对应该图第 i 条"""
    w, h = img.size
    cols = [_dominant(img.crop((i * w // n, 0, (i + 1) * w // n, h))) for i in range(n)]
    return _normalize_values(cols)


def cover_columns(img_bytes, n=8):
    """
    空间排布：按水平方向把封面切成 n 条，每列取主色。
    灯珠 i 对应封面的第 i 列 —— 灯带从左到右就是封面从左到右。
    """
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img = img.resize((n * 6, 48), Image.BILINEAR)
    return _columns_from_image(img, n)


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
        self.columns = []                     # 按封面从左到右取色
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
        self.columns = cover_columns(data)
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
MIC_ORDER = list(range(LED_COUNT))                        # [0,1,...,7] 近 -> 远（默认）
MIC_ORDER_REVERSED = list(range(LED_COUNT - 1, -1, -1))   # [7,...,0] 远 -> 近

# ---- 音量 -> 亮灯颗数 / 亮度 ----
# 颗数和亮度都跟着归一化电平 lv 一路走到 1.0 才满档，让 8 颗灯尽量覆盖整个电平范围：
#   lv < 0.02  -> 0 颗全灭（没声音）
#   lv = 0.10  -> 约 1.7 颗 / 1% 最终 PWM 占空比
#   lv = 1.00  -> 8 颗 / 80% 最终 PWM 占空比
# 亮度必须按最终占空比直出，不能过 gamma：gamma(0.1)≈0.4/255，10% 会肉眼全黑。
MIC_SOUND_GATE = 0.02        # 低于此 = 没声音/极低声：**一颗都不亮**
MIC_BRIGHT_STOPS = (         # (电平, 最终 PWM 占空比)，分段线性、单调递增
    (0.00, 0.00),
    (0.10, 0.01),           # 低电平很暗：1%
    (1.00, 0.80),           # 最大声 80%，不再冲到 95%
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
MIC_LEVEL_TAU = 0.035        # 电平快平滑（100Hz 下约 3~4 帧），波形跟手但不抖
MIC_SMOOTH_TAU = 0.035       # 声音驱动灯效的颜色平滑；全局 0.15s 会把波形削平

# ---- 放歌时：系统输出峰值驱动封面配色灯 ----
# 读默认输出设备的 IAudioMeterInformation（同一套 COM 代码，只是端点从
# eCapture 换成 eRender），不开捕获流、不碰 ConsentStore、戴耳机也照样有值。
RENDER_NOISE_FLOOR = 0.0     # 数字输出没有底噪，静音就是 0
RENDER_FULL_PEAK = 1.00      # 满档对应的输出峰值（--render-full-peak 可调）
# 放歌是「PWM 域」亮度系数：封面色必须**先逐通道过 gamma** 再乘它，
# 否则等于把感知颜色直接当 PWM 发出去，亮通道拉满、暗通道也被抬起 → 泛白过曝。
# 0.37 让白色封面最亮约 94/255，正好等于旧封面呼吸的 gamma(255×0.70)=93。
# 亮度从 RENDER_BRIGHT_FLOOR=0.01 线性爬升到 0.37：1% 是**曲线的起点**，
# 不是「低音量段固定不变」的保底平台 —— 后者才会被看成「声音很小灯却很亮」。
# 这里全程随 lv 连续变化。数字输出没有底噪，也不套麦克风声音门限，颗数至少 1 颗。
RENDER_BRIGHT_MAX = 0.37
RENDER_BRIGHT_FLOOR = 0.01
# 真静音（数字输出精确为 0，没有底噪）时一颗都不亮；刚过门限的极小声仍从 1% 起步。
# 只用来区分「完全没声音」和「有一点声音」，别调大，否则会吞掉小音量段。
RENDER_SILENCE_GATE = 0.005
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

    def __init__(self, full_peak=MIC_FULL_PEAK, noise_floor=MIC_NOISE_FLOOR):
        self.value = 0.0        # 平滑后的电平，灯效读这个
        self.peak = 0.0         # 本次原始峰值，面板显示
        self.noise_floor = float(noise_floor)
        self.full = max(self.noise_floor + 1e-3, float(full_peak))   # 满档峰值
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
        k = 1.0 - math.exp(-dt / MIC_LEVEL_TAU)
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
    """第 i 颗（按亮起顺序）的色相：120° 绿 -> 60° 黄 -> 30° 橙 -> 0° 红"""
    t = i / max(1, LED_COUNT - 1)
    return MIC_HUE_FIRST + (MIC_HUE_LAST - MIC_HUE_FIRST) * t


def mic_led_count(level):
    """电平 -> 亮起颗数（0 或 1.0~8.0，含小数）。

    低于 MIC_SOUND_GATE 直接 0 颗（没声音就全灭）；之后按 1 + lv×7 线性长，
    **lv=1.0 才刚好 8 颗**，让 8 颗灯覆盖整个电平范围而不是提前到顶。
    """
    lv = max(0.0, min(1.0, level))
    if lv < MIC_SOUND_GATE:
        return 0.0
    return 1.0 + lv * (LED_COUNT - 1)


def mic_brightness(level):
    """电平 -> 最终 PWM 占空比（0~1）。按 MIC_BRIGHT_STOPS 分段线性插值。

    注意这是「占空比」不是「感知亮度」：lv=0.1 的 1% 到 lv=1.0 的 80% 是灯珠
    实际发出来的比例，必须绕过 gamma，否则低段全被压成 0。门限以下直接 0。
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
    """放歌用的 PWM 域亮度系数：从 RENDER_BRIGHT_FLOOR(1%) 线性升到 RENDER_BRIGHT_MAX。

    1% 是**起点**而不是「低音量段固定不变」的保底平台 —— 后者会让人觉得
    声音很小灯却很亮。这里全程随 lv 连续变化。
    故意不复用 VU 的亮度曲线（那条低段被压得过暗）。media 帧和终端面板共用；
    调用方必须先把封面色过 gamma。
    """
    lv = max(0.0, min(1.0, level))
    return RENDER_BRIGHT_FLOOR + (RENDER_BRIGHT_MAX - RENDER_BRIGHT_FLOOR) * lv


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
    """麦克风态的 8 颗颜色（**已经是最终 PWM 值**，调用方要按 raw 直出）。

    in_use=False -> 全灭（待机：灯带与板载 LED 都灭，完全静默）。
    in_use=True  -> 音量同时决定亮几颗、什么颜色、多亮；
                    低于 MIC_SOUND_GATE 一颗都不亮，只有真有声音才亮起来。
    """
    if not in_use:
        return [(0, 0, 0)] * LED_COUNT
    order = mic_order(reverse)
    out = [(0, 0, 0)] * LED_COUNT
    n = mic_led_count(level)
    bright = mic_brightness(level)
    whole = int(n)
    frac = n - whole
    for i, idx in enumerate(order):
        if i >= whole:
            break
        c = hsv_to_rgb(mic_hue(i), MIC_SAT, MIC_VALUE)
        # 只有「正在长出来的那一颗」按小数渐入；整条再统一乘当前亮度
        k = bright * (frac if (i == whole - 1 and frac > 0.06) else 1.0)
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

STATE_COLOR = {"media": (205, 110, 255), "mic": (90, 200, 110), "idle": (120, 120, 140)}
STATE_LABEL = {"media": "音乐呼吸", "mic": "麦克风电平", "idle": "空闲"}


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
    def render(self, mon, frame, fps):
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
                col = hsv_to_rgb(mic_hue(lv * (LED_COUNT - 1)), MIC_SAT, 0.90)
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
            blocks = "".join(bg(c, "  " * max(1, round(w * 9))) for c, w in m.palette)
            L.append(self._row(f"配色 {blocks}  {len(m.palette)} 色"))
        rm = getattr(mon, "render_meter", None)
        if st == "media" and rm and rm.available:
            lv = mon.render_level.value
            # 放歌不套麦克风 VU 的 0.02 声音门限，颗数直接按 1 + lv×7 显示；
            # 用 mic_led_count() 会在极低音量显示「0.0 颗」而实际亮着 1 颗。
            L.append(self._row(f"输出 {1.0 + lv * (LED_COUNT - 1):.1f}/{LED_COUNT} 颗  "
                               f"亮度 {render_brightness(lv):.0%}  "
                               f"峰值 {mon.render_level.peak:.3f}"))
        if frame:
            L.append(self._row("灯珠 " + "".join(bg(c, "  ") for c in frame)))
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
                parts.append(f"麦克风 {mic_led_count(lv):.1f}/8 颗 "
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
# 渲染帧率 100Hz：输出峰值由 Windows 音频引擎按约 10ms 的设备周期更新，
# 50Hz 采样容易重复读同一值 / 漏掉瞬态，100Hz 才贴得上。
# 串口每帧 29 字节 × 100 = 2900 B/s，占 115200 的 25.2%，仍很宽裕；
# ESP8266 刷 8 颗 WS2812 只要 0.24ms，10ms 间隔绰绰有余。
# 实测 GetPeakValue 约 41µs、整帧纯计算约 59µs，100Hz 下占 CPU 约 0.6%。
# 所有平滑时间常数都按秒定义（或由 FRAME_INTERVAL 推导），帧率翻倍不改手感。
FRAME_HZ = 100
FRAME_INTERVAL = 1.0 / FRAME_HZ
# 固件侧全局亮度。默认满档 —— 亮度限制统一交给下面的 MAX_LEVEL，
# 固件侧不再二次打折：两道相乘会把 70% 压成 37%（128/255 × 0.70），灯明显偏暗。
# 真要限制电流就调 --max-level，它是唯一旋钮。
DEFAULT_BRIGHTNESS = 255
# host 侧输出上限（0~1），在 gamma 之前乘到每颗灯上 —— 降级封面呼吸受它限制。
# 两种声音驱动灯效是例外：亮度按最终 PWM 占空比直出
# （见 MIC_BRIGHT_STOPS / render_brightness / set_all(raw=True)）。
# 放歌先把封面色过 gamma（避免泛白过曝），最亮白色封面约 94/255，
# 与旧封面呼吸相当；VU 峰值 80%（饱和单色，电流仍低于 8 颗全白）。
# 70% 感知亮度对应 PWM gamma(178)=93，8 颗约 173mA，加板子约 250mA，离 USB 500mA 还有余量。
MAX_LEVEL = 0.70

# ---------------- 呼吸参数 ----------------
BREATHE_PERIOD = 4.0          # 一次完整呼吸的秒数（亮 -> 暗 -> 亮）
BREATHE_DEPTH = 0.40          # 呼吸幅度：亮度在 (1-depth) ~ 1 之间起伏
MEDIA_FALLBACK_DELAY = 1.5    # 音乐停多久才熄灯（防切歌/暂停空档闪灭）
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
    """按权重把封面配色铺到灯带上：权重大的颜色占多颗灯，呈现封面的配色比例"""
    if not palette:
        return [(0, 0, 0)] * n
    out = []
    for color, weight in palette:
        out += [color] * max(1, round(n * weight))
    if len(out) < n:
        out += [out[-1]] * (n - len(out))
    return out[:n]


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
    """把 8 颗里「黑灯」换成同一张封面采到的其它非黑颜色。

    候选池只取这张封面真实采到的保留色（按原顺序去重），不凭空造色；
    黑位按位置轮转取色 —— 确定性、不随机、切歌不会闪，也不会让连成一片的
    黑区全变成同一个颜色。整张封面全黑、没有候选时，取最亮那颗保留色相
    提亮到可见明度，8 颗统一用它（纯黑图退化为中性灰）。
    """
    base = list(base[:LED_COUNT])
    while len(base) < LED_COUNT:
        base.append(base[-1] if base else (0, 0, 0))
    dark = [i for i, c in enumerate(base) if is_black_led(c)]
    if not dark:
        return base
    pool = []
    for i, c in enumerate(base):
        if i not in dark and c not in pool:
            pool.append(c)
    if not pool:
        brightest = max(base, key=lambda c: max(apply_gamma(c)))
        h, s, _ = colorsys.rgb_to_hsv(*[c / 255 for c in brightest])
        r, g, b = colorsys.hsv_to_rgb(h, s, DARK_FALLBACK_VALUE)
        return [(round(r * 255), round(g * 255), round(b * 255))] * LED_COUNT
    out = list(base)
    for seq, i in enumerate(dark):
        out[i] = pool[seq % len(pool)]
    return out


class LinkLost(Exception):
    """串口断链：拔线 / 睡眠唤醒 / 驱动重枚举 / 写超时"""


class LedStrip:
    def __init__(self, port: str, baud: int = 115200, max_level=MAX_LEVEL):
        self.port_name = port
        self.baud = baud
        self.brightness = None
        self.max_level = max(0.0, min(1.0, max_level))
        self._status_led = None      # 上次发过的板载 LED 灯态（None=未知，重连后要重发）
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

    def handshake(self, timeout: float = 1.5) -> bool:
        """确认对面是期望的固件，避免把数据发给了别的程序/别的固件"""
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
                pos = buf.find(bytes([HDR0, HDR1]))
                if pos >= 0 and len(buf) >= pos + 6:
                    body = bytes(buf[pos + 2:pos + 5])      # cmd, len, payload
                    crc = buf[pos + 5]
                    if body[0] == CMD_HANDSHAKE and crc8(body) == crc:
                        print(f"  握手成功，固件版本 v{body[2]}")
                        return True
                    del buf[:pos + 2]
        except Exception as e:
            raise LinkLost(f"握手时断链：{type(e).__name__}: {e}") from e
        print("  握手失败：没收到固件回应（确认烧的是本项目固件，且串口监视器没开着）")
        return False

    def set_all(self, rgb_list, raw=False):
        """raw=True：rgb_list 已是最终 PWM 值（0~255），直接发，绕过 gamma 与 max_level。

        声音驱动灯效（放歌封面灯 / 麦克风 VU）必须用这个模式：它们给的
        1%~37% / 1%~80% 是「最终占空比」，过一遍 gamma 会把 1% 压成 0/255、
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
        闪的节奏由固件按毫秒自己走，不受主循环 100Hz 帧率的限制。"""
        times = max(1, min(10, int(times)))
        self._write(build_frame(CMD_STATUS_PULSE, bytes([times])))

    def off(self):
        try:
            self._write(build_frame(CMD_OFF))
            self.set_status_led(STATUS_LED_OFF)
            time.sleep(0.05)
        except Exception:
            pass

    # ---------- 断线重连 ----------

    def find_port(self):
        """优先用原端口名；找不到就按 CH340 描述匹配（睡眠唤醒后端口号可能变）"""
        ports = list(list_ports.comports())
        if any(p.device == self.port_name for p in ports):
            return self.port_name
        for p in ports:
            desc = (p.description or "").lower()
            if "ch340" in desc or "usb-serial" in desc or "usb serial" in desc:
                return p.device
        return None

    def reconnect(self, stop_event=None, max_delay: float = 30.0, log=print) -> bool:
        """
        指数退避重连：1 → 2 → 4 → 8 …（上限 max_delay 秒），连上即重置延迟。
        stop_event 置位则放弃并返回 False。
        """
        delay, attempt = 1.0, 0
        while not (stop_event and stop_event.is_set()):
            attempt += 1
            port = self.find_port()
            if port:
                try:
                    self.close()
                    self.port_name = port
                    self.open()
                    log(f"  重连成功（第 {attempt} 次）：{port}")
                    return True
                except Exception as e:
                    log(f"  重连失败（第 {attempt} 次，{port}）：{type(e).__name__}: {e}")
            else:
                log(f"  未找到串口（第 {attempt} 次），{delay:.0f}s 后重试…")
            end = time.time() + delay
            while time.time() < end:
                if stop_event and stop_event.is_set():
                    return False
                time.sleep(0.2)
            delay = min(delay * 2, max_delay)
        return False

    def resume(self) -> bool:
        """重连后恢复运行时状态：重新握手 + 重放亮度"""
        self._status_led = None          # 固件可能刚重启，板载灯态缓存作废，必须重发
        ok = self.handshake()
        if self.brightness is not None:
            self.set_brightness(self.brightness)
        return ok


# ============================================================
# 主控
# ============================================================
class Monitor:
    """
    三个状态，优先级从高到低：
      media  正在播放 -> 铺封面配色，输出峰值决定亮几颗/多亮（端点不可用才降级成整条呼吸）
      mic    没在播放 -> 麦克风没占用=灯带全灭+板载也灭 / 正在录音=按音量亮 1~8 颗
      idle   没在播放且麦克风检测不可用 -> 熄灭（只有非 Windows 才会落到这）

    切歌/暂停不立刻熄灯，留 MEDIA_FALLBACK_DELAY 的缓冲，避免空档闪灭。
    注册表占用和电平峰值在所有状态下都持续轮询，从 media 切回来时数据是现成的。
    """

    def __init__(self, app_filter=None, cover_layout="spatial",
                 breathe_period=BREATHE_PERIOD, breathe_depth=BREATHE_DEPTH,
                 mic=True, mic_reverse=False, status_led=True,
                 mic_full_peak=MIC_FULL_PEAK, render_full_peak=RENDER_FULL_PEAK):
        self.cover_layout = cover_layout
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
        self.level = MicLevel(mic_full_peak) if mic else None
        # 放歌时读系统输出峰值：与麦克风完全独立，--no-mic 也照常可用
        self.render_meter = MicLevelMeter(0, 0)
        self.render_level = MicLevel(render_full_peak, RENDER_NOISE_FLOOR)
        self.mic_reverse = bool(mic_reverse)
        self._raw_frame = False      # 电平表按最终 PWM 直出；其它灯效走 gamma
        self.state = "media"
        self._media_off_since = None        # 音乐断了多久（缓冲计时）
        self.current = [(0, 0, 0)] * LED_COUNT
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

    def compute_target(self):
        now = time.time()
        # 不管当前是哪一态都持续轮询：从 media 切回来时判定与电平都得是现成的
        if self.mic:
            self.mic.poll(now)
        if self.meter:
            self.level.update(self.meter.read(), now)
        if self.render_meter and self.render_meter.available:
            self.render_level.update(self.render_meter.read(), now)

        if self._media_on():
            self._media_off_since = None
            new_state = "media"
        else:
            if self._media_off_since is None:
                self._media_off_since = now
            stay = (self.state == "media"
                    and (now - self._media_off_since) < MEDIA_FALLBACK_DELAY)
            if stay:
                new_state = "media"
            else:
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

        if self.state == "media" and self.media.color:
            base = self._cover_base()
            if not (self.render_meter and self.render_meter.available):
                # 降级：这台机器的输出端点读不到峰值，回到原来的整条封面呼吸
                phase = (now % self.breathe_period) / self.breathe_period
                wave = 0.5 - 0.5 * math.cos(2 * math.pi * phase)
                level = (1.0 - self.breathe_depth) + self.breathe_depth * wave
                return [scale(c, level) for c in base]

            # 声音驱动：颜色仍是这 8 颗封面配色，亮几颗 / 多亮交给系统输出峰值。
            # 封面色先逐通道过 gamma 转成 PWM 域 —— 这一步不能省：
            # 直接拿感知 RGB 乘系数再 raw 直出会过曝泛白（亮暗通道一起被抬起来）。
            # 过完 gamma，最亮的白色封面约 94/255，与旧封面呼吸的最亮帧一致。
            lv = self.render_level.value
            self._raw_frame = True          # current 是 PWM 域，静音那帧也不能再过一次 gamma
            # 真静音：数字输出精确为 0（没有底噪），一颗都不亮。
            # 刚过门限的极小声仍走下面的 1% 起步，两者不冲突；靠 0.035s 平滑柔和淡出。
            if self.render_level.peak < RENDER_SILENCE_GATE:
                return [(0, 0, 0)] * LED_COUNT
            gamma_base = [apply_gamma(c) for c in base]
            n = 1.0 + lv * (LED_COUNT - 1)   # 颗数不做门限；亮度另由 render_brightness 从 1% 起步
            bright = render_brightness(lv)
            # 保底强度随亮度缩放：静音侧约 1/255、满档 18/255，全程连续，
            # 既不会让深色封面锁在同一个亮度，也不会「补了还是看不见」。
            glow_level = RENDER_MIN_GLOW * bright / RENDER_BRIGHT_MAX
            out = [(0, 0, 0)] * LED_COUNT
            whole, frac = int(n), n - int(n)
            # 小数部分必须用在「正在长出来的下一颗」上。旧写法 i < whole 只亮 whole
            # 颗，却把 frac 乘在 i==whole-1 上：面板说 7.3 颗、实际只有 7 颗，
            # 而且第 7 颗被削暗；第 8 颗要 n>=8.0（lv 精确 1.0）才可能出现。
            # 现在 whole 颗满亮 + 第 whole 颗按 frac 渐入；frac 太小就不点亮它，
            # 只剩 1 颗时也不渐入（避免极小声时自己忽明忽暗）。
            extra = 1 if (whole >= 2 and whole < LED_COUNT and frac > 0.06) else 0
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
        """灯珠基色：spatial=按封面从左到右取色（灯带左右对应封面左右），
        weight=按配色权重铺（主色占多颗）。两条路径最后都过一遍去黑回填，
        保证 8 颗里没有「采样到黑色、实际不发光」的灯珠。"""
        if self.cover_layout == "spatial" and self.media.columns:
            base = list(self.media.columns[:LED_COUNT])
            while len(base) < LED_COUNT:
                base.append(base[-1])
        else:
            base = palette_to_leds(self.media.palette)
        return fill_dark_leds(base)

    def tick(self, strip: LedStrip):
        target = self.compute_target()
        # 声音驱动的两种态（录音 VU / 放歌封面灯）都要跟得上波形：0.15s 会削平。
        # 待机全灭、以及输出端点不可用时的降级呼吸仍用 0.15s，过渡更柔和。
        sound_driven = ((self.state == "mic" and self.mic and self.mic.in_use)
                        or (self.state == "media" and self.render_meter
                            and self.render_meter.available))
        tau = MIC_SMOOTH_TAU if sound_driven else SMOOTH_TAU
        k = 1.0 - math.exp(-FRAME_INTERVAL / tau)
        self.current = [lerp_rgb(c, t, k) for c, t in zip(self.current, target)]
        strip.set_all(self.current, raw=self._raw_frame)
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
TASK_NAME = "ESP-WS2812 音乐封面呼吸灯"
STARTUP_VBS_NAME = "ESP-WS2812 音乐封面呼吸灯.vbs"
DEFAULT_WAIT_PORT = 30           # 开机自启时给 USB 枚举 / 固件启动留的秒数


def _task_description():
    """任务计划程序里「描述」那一栏写的备注 —— 以后忘了这是啥，看它就够了"""
    script = os.path.join(BASE_DIR, "led_host.py")
    return (
        "【ESP-WS2812 音乐封面呼吸灯】开机自启的后台灯效。\n"
        f"做什么：读取系统正在播放的音乐的专辑封面配色，铺到 WeMOS D1 mini 上的 "
        f"{LED_COUNT} 颗 WS2812B 灯珠，整条灯带缓慢呼吸；"
        f"音乐停止 {MEDIA_FALLBACK_DELAY:g} 秒后自动熄灯。\n"
        f"主脚本：{script}\n"
        f"日志文件：{LOG_PATH}\n"
        "临时停一次：python led_host.py --autostart stop\n"
        "彻底卸载：python led_host.py --autostart remove\n"
        "为什么不是 Windows 服务：服务运行在 Session 0，与用户会话隔离，"
        "SMTC 媒体接口在那里恒返回空，灯永远不亮，所以用的是任务计划程序。"
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
    """后台模式：终端一个字都不输出，全部进日志文件，另外记下 pid 方便停"""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".old")
    except OSError:
        pass
    f = open(LOG_PATH, "a", encoding="utf-8")
    sys.stdout = _Timestamped(f)
    sys.stderr = sys.stdout
    try:
        with open(PID_PATH, "w", encoding="utf-8") as pf:
            pf.write(str(os.getpid()))
    except OSError:
        pass
    print(f"--- 后台启动 ---  {' '.join(sys.argv)}")


# ---------------- Windows 侧的小工具 ----------------

def _decode(b):
    for enc in ("utf-8", "cp936"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def _schtasks(args):
    """schtasks 中文输出是 GBK，统一解码后再看"""
    p = subprocess.run(["schtasks"] + args, capture_output=True)
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
    """装机时把这次的参数固化进去，以后每次自启都用同一套"""
    parts = ["--port", str(args.port), "--baud", str(args.baud),
             "--brightness", str(args.brightness),
             "--max-level", f"{args.max_level:g}",
             "--cover-layout", args.cover_layout,
             "--breathe-period", f"{args.breathe_period:g}",
             "--breathe-depth", f"{args.breathe_depth:g}",
             "--mic-full-peak", f"{args.mic_full_peak:g}",
             "--render-full-peak", f"{args.render_full_peak:g}"]
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
        print("          任务计划程序库里能看到，点开「描述」写了它是干嘛的、怎么关")
        print("  触发  ：登录后 20 秒（等 USB 枚举完）")
    else:
        print(f"  启动器：{_startup_vbs_path()}")
        print("          在「启动」文件夹里，双击它也能立刻跑起来")
    print(f"  日志  ：{LOG_PATH}")
    print("  立刻跑：python led_host.py --autostart start")
    print("  临时停：python led_host.py --autostart stop")
    print("  彻底卸：python led_host.py --autostart remove")


def _install_startup_vbs(pyw, args_line):
    """降级方案：放一个 vbs 到「启动」文件夹。不需要管理员，但没有崩溃自动重启"""
    path = _startup_vbs_path()
    if not path:
        print("  找不到「启动」文件夹，装不了")
        return 1
    vbs = (
        "' ESP-WS2812 音乐封面呼吸灯 —— 开机自启启动器\r\n"
        "' 本文件由 led_host.py 自动生成，改参数请重新跑 --autostart install，别手改这里。\r\n"
        "'\r\n"
        "' 作用：登录 Windows 后无窗口启动 led_host.py，让 8 颗 WS2812B 灯珠\r\n"
        "'       跟着当前播放音乐的专辑封面配色呼吸；音乐停 1.5 秒后熄灯。\r\n"
        f"' 主脚本：{os.path.join(BASE_DIR, 'led_host.py')}\r\n"
        f"' 日志  ：{LOG_PATH}\r\n"
        "' 临时停：python led_host.py --autostart stop\r\n"
        "' 彻底卸：python led_host.py --autostart remove\r\n"
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
    print("  看现状：python led_host.py --autostart status")
    print("  或者用不需要管理员的方案：python led_host.py --autostart install --method startup")
    return 1


def _read_pid():
    try:
        with open(PID_PATH, encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
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
    if pid and _pid_alive(pid):
        print(f"  后台进程：正在运行（pid {pid}）")
    else:
        print("  后台进程：没在跑")
    print(f"  日志：{LOG_PATH if os.path.exists(LOG_PATH) else '（还没有日志）'}")
    return 0


def autostart_stop():
    _schtasks(["/end", "/tn", TASK_NAME])     # 先结束任务实例，否则会被「失败重启」策略拉回来
    pid = _read_pid()
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
    rc, out, err = _schtasks(["/run", "/tn", TASK_NAME])
    if rc == 0:
        print("  已让计划任务立刻启动一次（几秒后看 --autostart status 确认）。")
        return 0
    print("  计划任务没注册，直接后台启动一次：")
    pyw = _pythonw()
    subprocess.Popen([pyw, os.path.abspath(__file__), "--background",
                      "--wait-port", f"{DEFAULT_WAIT_PORT:g}"],
                     cwd=BASE_DIR, close_fds=True)
    print("  已启动。要开机也自动跑，先跑 --autostart install。")
    return 0


def autostart_remove():
    autostart_stop()
    rc, out, err = _schtasks(["/delete", "/tn", TASK_NAME, "/f"])
    print(f"  计划任务：{'已删除' if rc == 0 else '本来就没注册'}")
    _remove_startup_vbs()
    print("  启动文件夹：已清理")
    print("\n自启已卸掉。灯现在是灭的，想再手动跑就 python led_host.py。")
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
def connect(port, baud, wait=0.0, max_level=MAX_LEVEL):
    """打开串口 + 握手。wait>0 时开机场景能等：USB 枚举和固件启动可能慢半拍"""
    deadline = time.time() + max(0.0, wait)
    attempt = 0
    while True:
        attempt += 1
        try:
            strip = LedStrip(port, baud, max_level)
        except Exception as e:
            if time.time() >= deadline:
                raise
            if attempt == 1 or attempt % 5 == 0:
                print(f"  串口 {port} 打不开（{type(e).__name__}: {e}），继续等…")
            time.sleep(1.0)
            continue
        if strip.handshake():
            return strip
        if time.time() >= deadline:
            return strip                      # 握手不上也先跑，可能只是固件版本老
        print("  握手没成功，固件可能还没起来，重试…")
        strip.close()
        time.sleep(1.0)


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

    print("[demo] 单灯扫描 2 轮：验证 8 颗灯珠能被独立寻址")
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
          f" / 声音门限 {MIC_SOUND_GATE:g}（低于此一颗都不亮） / 平滑 {MIC_LEVEL_TAU:g}s")
    print("  校准：python led_host.py --mic-calibrate（说话 5 秒，直接给建议值）")
    print("  电平预览（近 -> 远，绿 -> 黄 -> 橙 -> 红；色块亮度 = 最终 PWM 占空比）：")
    for lv in (0.0, 0.02, 0.10, 0.30, 0.50, 0.70, 0.90, 1.0):
        cols = mic_leds(True, lv)
        print(f"    {lv:.2f} -> {mic_led_count(lv):.1f} 颗 / "
              f"{mic_brightness(lv):>3.0%}  " + "".join(bg(c, "  ") for c in cols))
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
                mic_full_peak=MIC_FULL_PEAK, render_full_peak=RENDER_FULL_PEAK):
    mon = Monitor(app_filter, cover_layout, breathe_period, breathe_depth,
                  mic, mic_reverse, status_led, mic_full_peak, render_full_peak)
    if mon.media.available:
        print("[monitor] 音乐封面呼吸灯")
        if mon.render_meter.available:
            print(f"          播放中 -> 封面配色 + 系统输出峰值驱动（{cover_layout}，"
                  f"满档 {render_full_peak:g}，颗数/亮度随音量）")
            print(f"          真静音 peak<{RENDER_SILENCE_GATE:g} 全灭；"
                  f"极小声从 {RENDER_BRIGHT_FLOOR:.0%} 起步")
        else:
            print(f"          播放中 -> 封面配色 + 呼吸（{cover_layout}，"
                  f"周期 {breathe_period:g}s，幅度 {breathe_depth:.2f}）"
                  "  [输出端点不可用，降级]")
    else:
        print("[monitor] 媒体源不可用（缺 WinRT/Pillow），只会走麦克风指示")
    if mon.mic and mon.mic.available:
        print(f"          没在播放 -> 静音 {MEDIA_FALLBACK_DELAY:g}s 后切过去："
              f"未占用=灯带全灭+板载也灭 / 录音中=颗数+颜色+亮度都跟音量走")
        if mon.meter and mon.meter.available:
            print(f"          电平 {FRAME_HZ}Hz · 绿->黄->橙->红 · "
                  f"{'远 -> 近' if mic_reverse else '近 -> 远'}（--mic-reverse 可翻转）"
                  f" · 亮度 1%~80% · lv=1.0 才 8 颗")
            print(f"          固定量程 peak {MIC_NOISE_FLOOR:g}~{mic_full_peak:g}"
                  f"（--mic-calibrate 实测 / --mic-full-peak 校准）"
                  f" · 低于 {MIC_SOUND_GATE:g} 全灭")
    else:
        print(f"          没在播放 -> 静音 {MEDIA_FALLBACK_DELAY:g}s 后熄灯")
    print(f"          降级呼吸走 gamma + {strip.max_level:.0%} 上限（--max-level）；"
          f"声音驱动灯效按最终 PWM 直出（放歌 {RENDER_BRIGHT_FLOOR:.0%}~"
          f"{RENDER_BRIGHT_MAX:.0%} / VU 80%）；"
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
                if not strip.reconnect(mon.stop_event):
                    print("    已放弃重连，退出。")
                    break
                strip.resume()
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
                dsp.render(mon, mon.current, fps)
                last_ui = t0

            time.sleep(max(0.0, FRAME_INTERVAL - (time.time() - t0)))
    finally:
        dsp.finish()                       # 先把光标移到面板下方，后续输出才不会盖住面板
        mon.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="COM4")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--brightness", type=int, default=DEFAULT_BRIGHTNESS,
                    help=f"固件侧全局亮度 0-255（默认 {DEFAULT_BRIGHTNESS}），"
                         "8 颗满亮约 480mA，别开太高")
    ap.add_argument("--max-level", type=float, default=MAX_LEVEL, metavar="X",
                    help=f"降级封面呼吸的输出上限 0~1（默认 {MAX_LEVEL:g}）。"
                         "声音驱动灯效按自己的亮度曲线直出，不受它限制")
    ap.add_argument("--no-mic", action="store_true",
                    help="关掉麦克风指示：没播音乐就熄灯，板载 LED 也灭")
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
                    help="封面取色方式：spatial 按封面从左到右(灯带左右对应封面左右，默认) / "
                         "weight 按配色权重铺(主色占多颗)；两种都不会出现黑灯")
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

    if args.render_calibrate:
        calibrate_render()
        return 0

    if args.mic_calibrate:
        calibrate_mic()
        return 0

    if args.diagnose:
        diagnose(args.watch, args.mic_full_peak)
        return 0

    print(f"打开 {args.port} @ {args.baud} ...")
    try:
        strip = connect(args.port, args.baud, args.wait_port, args.max_level)
    except Exception as e:
        print(f"打不开串口：{e}")
        print("常见原因：Arduino IDE 串口监视器没关 / 串口号不对 / 板子没插")
        return 1

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
                        render_full_peak=args.render_full_peak)
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
