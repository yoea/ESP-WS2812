#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MSI Mystic Light 主板灯控 —— 纯 Python，零第三方依赖。

适用：使用「通用 PID」 0x0DB0:0x0076 的微星主板，走 185 字节协议。
      已在 MSI MAG B760M MORTAR II (MS-7E13) 上验证。

协议来源：OpenRGB 的 MSIMotherboard185Controller（GPL-2.0-or-later），
          由 @t-bond / @CalcProgrammer1 / @garashchenko 逆向。

两条通路：
  0x52 / 185 字节   区域配置：每个灯区的「效果 + 颜色 + 亮度」
  0x53 / 725 字节   每灯直控：[0x53, hdr0, hdr1, hdr2, hdr3] + 240 × RGB

安全约定：save 标志默认 0 —— 只改控制器内存，不写 flash，重启即恢复。
          想持久化必须显式加 --save，请谨慎。
"""

import argparse
import colorsys
import ctypes
import math
import sys
import time
from ctypes import byref, wintypes

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ─────────────────────────── 设备与协议常量 ───────────────────────────

VID_MSI = 0x0DB0
PID_COMMON = 0x0076

RPT_ZONE = 0x52
RPT_PERLED = 0x53
LEN_ZONE = 185
LEN_PERLED = 725
NUM_PER_LED = 240          # 0x53 报文固定带 240 颗灯的槽位

MSI_DIRECT_MODE = 0x25     # 直控模式的「效果」值（不在 MSI_MODE 枚举里）

MODE_DISABLE = 0
MODE_STATIC = 1
MODE_BREATHING = 2

# MSI_MODE 枚举 —— 取自 OpenRGB MSIMotherboardCommon.h（185 字节协议通用）
# 键名用于 --effect，允许空格/下划线混写（内部会归一化）
MODES = {
    "disable":                    (0,  "关闭"),
    "static":                     (1,  "常亮（整口单色）"),
    "breathing":                  (2,  "呼吸"),
    "flashing":                   (3,  "闪烁"),
    "double flashing":            (4,  "双闪"),
    "lightning":                  (5,  "闪电"),
    "msi marquee":                (6,  "跑马灯"),
    "meteor":                     (7,  "流星"),
    "water drop":                 (8,  "水滴"),
    "msi rainbow":                (9,  "彩虹 · A"),
    "pop":                        (10, "律动 POP"),
    "rap":                        (11, "律动 RAP"),
    "jazz":                       (12, "律动 JAZZ"),
    "play":                       (13, "律动 PLAY"),
    "movie":                      (14, "影院"),
    "color ring":                 (15, "光环"),
    "planetary":                  (16, "行星"),
    "double meteor":              (17, "双流星"),
    "energy":                     (18, "能量"),
    "blink":                      (19, "呼吸灯（快闪）"),
    "clock":                      (20, "时钟"),
    "color pulse":                (21, "色彩脉动"),
    "color shift":                (22, "色彩偏移"),
    "color wave":                 (23, "色彩波浪"),
    "marquee":                    (24, "跑马灯（长）"),
    "rainbow":                    (25, "彩虹 · B"),
    "rainbow wave":               (26, "彩虹波 ★ 推荐"),
    "visor":                      (27, "护目镜"),
    "jrainbow":                   (28, "彩虹 · ARGB 口专用 ★"),
    "rainbow flashing":           (29, "彩虹闪烁"),
    "rainbow double flashing":    (30, "彩虹双闪"),
    "random":                     (31, "随机"),
    "fan control":                (32, "风扇控制（非灯效）"),
    "disable2":                   (33, "关闭 2"),
    "color ring flashing":        (34, "光环闪烁"),
    "color ring double flashing": (35, "光环双闪"),
    "stack":                      (36, "堆叠"),
    "corsair que":                (37, "海盗船队列"),
    "fire":                       (38, "火焰"),
    "lava":                       (39, "岩浆"),
}
MODE_NAME = {v: k for k, (v, _) in MODES.items()}

# 速度档（协议里占 rec[4] 的 bit0-1）
SPEEDS = {"low": 0, "medium": 1, "high": 2}

# 「彩虹 / 流光」类效果：颜色由控制器自己生成，我们给的 color1/color2 不起作用
RAINBOW_LIKE = {
    9, 15, 16, 17, 25, 26, 28, 29, 30, 34, 35, 36,
}

COLOR_FLAG_USE_CUSTOM = 0x80
SYNC_FLAG_JRGB = 0x80

# 每灯报文的头字节：(hdr0, hdr1, hdr2, hdr3)
PERLED_HDR = {
    "onboard_sync": (0x25, 6, 0, 0),
    "jrainbow1":    (0x25, 4, 0, 0),
    "jrainbow2":    (0x25, 4, 1, 0),
    "jcorsair":     (0x25, 5, 0, 0),
}

# OpenRGB 的同步直控上限：JRAINBOW 每条最多 40 颗时走「单包合并」模式
SYNC_JRAINBOW_LEDS = 40
SYNC_CORSAIR_LEDS = 120

# ─────────────────────────── 灯区（MSI_ZONE） ───────────────────────────

J_RGB_1, J_RGB_2 = 1, 2
J_PIPE_1, J_PIPE_2 = 3, 4
J_RAINBOW_1, J_RAINBOW_2, J_RAINBOW_3 = 8, 9, 10
J_CORSAIR = 11
J_CORSAIR_OUTERLL120 = 12
ON_BOARD_LED_0 = 13

ZONE_NAME = {
    J_RGB_1: "JRGB1", J_RGB_2: "JRGB2",
    J_PIPE_1: "JPIPE1", J_PIPE_2: "JPIPE2",
    J_RAINBOW_1: "JARGB1", J_RAINBOW_2: "JARGB2", J_RAINBOW_3: "JARGB3",
    J_CORSAIR: "JCORSAIR", J_CORSAIR_OUTERLL120: "JCORSAIR_LL120",
    ON_BOARD_LED_0: "板载LED",
    ON_BOARD_LED_0 + 1: "板载LED1", ON_BOARD_LED_0 + 2: "板载LED2",
    ON_BOARD_LED_0 + 3: "板载LED3", ON_BOARD_LED_0 + 4: "板载LED4",
    ON_BOARD_LED_0 + 5: "板载LED5", ON_BOARD_LED_0 + 6: "板载LED6",
    ON_BOARD_LED_0 + 7: "板载LED7", ON_BOARD_LED_0 + 8: "板载LED8",
    ON_BOARD_LED_0 + 9: "板载LED9",
}

# 185 字节报文里各灯区记录的起始偏移（与 FeaturePacket_185 结构一致）
ZONE_OFFSET = {
    J_RGB_1: 0x01, J_PIPE_1: 0x0B, J_PIPE_2: 0x15,
    J_RAINBOW_1: 0x1F, J_RAINBOW_2: 0x2A, J_CORSAIR: 0x35,
    J_CORSAIR_OUTERLL120: 0x40, ON_BOARD_LED_0: 0x4A,
    ON_BOARD_LED_0 + 1: 0x54, ON_BOARD_LED_0 + 2: 0x5E,
    ON_BOARD_LED_0 + 3: 0x68, ON_BOARD_LED_0 + 4: 0x72,
    ON_BOARD_LED_0 + 5: 0x7C, ON_BOARD_LED_0 + 6: 0x86,
    ON_BOARD_LED_0 + 7: 0x90, ON_BOARD_LED_0 + 8: 0x9A,
    ON_BOARD_LED_0 + 9: 0xA4, J_RGB_2: 0xAE,
}
SAVE_OFFSET = 0xB8

# CorsairZoneData 的字段排布和普通 ZoneData 不同
CORSAIR_LIKE = {J_CORSAIR}

NAME_TO_ZONE = {
    "jrgb1": J_RGB_1, "jrgb2": J_RGB_2,
    "jpipe1": J_PIPE_1, "jpipe2": J_PIPE_2,
    "jargb1": J_RAINBOW_1, "jrainbow1": J_RAINBOW_1, "argb1": J_RAINBOW_1,
    "jargb2": J_RAINBOW_2, "jrainbow2": J_RAINBOW_2, "argb2": J_RAINBOW_2,
    "jargb3": J_RAINBOW_3, "jrainbow3": J_RAINBOW_3, "argb3": J_RAINBOW_3,
    "jcorsair": J_CORSAIR,
    "onboard": ON_BOARD_LED_0, "board": ON_BOARD_LED_0,
}

# 该板（0x0076 通用配置）的灯珠构成，用于同步直控时的数据排布
CFG_ONBOARD_LEDS = 0
CFG_PIPE1_LEDS = 0
CFG_PIPE2_LEDS = 0
CFG_JRGB_COUNT = 2


# ─────────────────────────── ctypes 绑定 ───────────────────────────

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HID_GUID = (0x4D1E55B2, 0xF16F, 0x11CF, (0x88, 0xCB, 0, 0x11, 0x11, 0, 0, 0x30))
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 1, 2
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_ulonglong)]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("DevicePath", ctypes.c_wchar * 512)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                ("InputReportByteLength", wintypes.USHORT),
                ("OutputReportByteLength", wintypes.USHORT),
                ("FeatureReportByteLength", wintypes.USHORT),
                ("Reserved", wintypes.USHORT * 17),
                ("NumberLinkCollectionNodes", wintypes.USHORT),
                ("NumberInputButtonCaps", wintypes.USHORT),
                ("NumberInputValueCaps", wintypes.USHORT),
                ("NumberFeatureButtonCaps", wintypes.USHORT),
                ("NumberFeatureValueCaps", wintypes.USHORT)]


hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetProductString.restype = wintypes.BOOL
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOL
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = wintypes.ULONG
hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetFeature.restype = wintypes.BOOL
hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_SetFeature.restype = wintypes.BOOL

kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                          wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
    ctypes.POINTER(SP_DEVICE_INTERFACE_DETAIL_DATA_W), wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]


def _parse_vidpid(path):
    low = path.lower()
    vid = pid = None
    i, j = low.find("vid_"), low.find("pid_")
    try:
        if i >= 0:
            vid = int(low[i + 4:i + 8], 16)
        if j >= 0:
            pid = int(low[j + 4:j + 8], 16)
    except ValueError:
        pass
    return vid, pid


def enumerate_hid(vid_wanted=VID_MSI, pid_wanted=PID_COMMON):
    """枚举 HID 接口。返回 [(vid, pid, path)]，以及可按需打开的句柄。"""
    guid = GUID()
    guid.Data1, guid.Data2, guid.Data3 = HID_GUID[0], HID_GUID[1], HID_GUID[2]
    for i, v in enumerate(HID_GUID[3]):
        guid.Data4[i] = v

    hdev = setupapi.SetupDiGetClassDevsW(byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdev == INVALID_HANDLE:
        return []
    out, idx = [], 0
    while True:
        iface = SP_DEVICE_INTERFACE_DATA()
        iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
        if not setupapi.SetupDiEnumDeviceInterfaces(hdev, None, byref(guid), idx,
                                                    byref(iface)):
            break
        idx += 1
        detail = SP_DEVICE_INTERFACE_DETAIL_DATA_W()
        detail.cbSize = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
        if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                hdev, byref(iface), byref(detail), ctypes.sizeof(detail), None, None):
            continue
        v, p = _parse_vidpid(detail.DevicePath)
        if v is None:
            continue
        if (vid_wanted is None or v == vid_wanted) and (pid_wanted is None or p == pid_wanted):
            out.append((v, p, detail.DevicePath))
    setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out


def parse_color(text):
    """'FF8800' / '#ff8800' / '255,136,0' -> (r, g, b)"""
    t = text.strip().lstrip("#").replace(",", " ")
    if " " in t:
        parts = [int(x) for x in t.split() if x]
        if len(parts) != 3:
            raise ValueError("颜色要写三个数：255,136,0")
        return tuple(max(0, min(255, v)) for v in parts)
    if len(t) != 6:
        raise ValueError("颜色要写 6 位十六进制，例如 FF8800")
    return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))


def rainbow_colors(n, start=0.0, span=1.0, level=1.0):
    """生成 n 颗灯的彩虹色：色相在 [start, start+span) 上均匀铺开，整体乘以 level 调亮度"""
    if n <= 0:
        return []
    return [tuple(int(v * 255 * level)
                  for v in colorsys.hsv_to_rgb((start + span * i / n) % 1.0, 1.0, 1.0))
            for i in range(n)]


def brightness_level(pct):
    """0-100% -> 0-10（协议里亮度是 5 位，取值 0..10）"""
    return max(0, min(10, round(pct / 10.0)))


def resolve_effect(name):
    """把用户输入的效果名归一化成 MODES 里的键；认不出来返回 None。
    容错：大小写、下划线/横杠/空格混写都接受（'rainbow_wave' == 'Rainbow Wave'）。"""
    s = " ".join(str(name).strip().lower().replace("_", " ").replace("-", " ").split())
    if s in MODES:
        return s
    squashed = s.replace(" ", "")
    for k in MODES:
        if k.replace(" ", "") == squashed:
            return k
    return None


# ─────────────────────────── 控制器封装 ───────────────────────────

class MysticLight185:
    def __init__(self):
        self.handle = None
        self.path = None
        self.product = ""
        self.feature_len = 0
        self.data = bytearray(LEN_ZONE)
        self.data[0] = RPT_ZONE

    # ---------- 设备 ----------

    def open(self):
        cands = enumerate_hid()
        if not cands:
            raise RuntimeError("没找到 0x0DB0:0x0076 的 HID 设备（微星 Mystic Light）")
        last_err = 0
        for v, p, path in cands:
            h = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                                     FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                     OPEN_EXISTING, 0, None)
            if h == INVALID_HANDLE:
                last_err = ctypes.get_last_error()
                continue
            self.handle = h
            self.path = path
            break
        if self.handle is None:
            raise RuntimeError(f"设备存在但打不开（错误码 {last_err}），请用管理员身份重跑")

        pbuf = ctypes.create_unicode_buffer(256)
        if hid.HidD_GetProductString(self.handle, pbuf, 512):
            self.product = pbuf.value.strip()

        pp = ctypes.c_void_p()
        if hid.HidD_GetPreparsedData(self.handle, byref(pp)):
            caps = HIDP_CAPS()
            if hid.HidP_GetCaps(pp, byref(caps)) == 0x110000:
                self.feature_len = caps.FeatureReportByteLength
            hid.HidD_FreePreparsedData(pp)
        return self

    def close(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    # ---------- 收发 ----------

    def read_zone(self):
        buf = ctypes.create_string_buffer(LEN_ZONE)
        buf[0] = bytes([RPT_ZONE])
        if not hid.HidD_GetFeature(self.handle, buf, LEN_ZONE):
            raise RuntimeError(f"读 0x52 失败（错误码 {ctypes.get_last_error()}）")
        self.data = bytearray(buf.raw[:LEN_ZONE])
        self.data[0] = RPT_ZONE
        return self.data

    def send_zone(self, packet=None):
        pkt = packet if packet is not None else self.data
        buf = ctypes.create_string_buffer(bytes(pkt), LEN_ZONE)
        if not hid.HidD_SetFeature(self.handle, buf, LEN_ZONE):
            raise RuntimeError(f"写 0x52 失败（错误码 {ctypes.get_last_error()}）")
        return True

    def send_perled(self, hdr, colors):
        """hdr = (hdr0, hdr1, hdr2, hdr3)；colors 是长度 ≤240 的 (r,g,b) 列表"""
        pkt = bytearray(LEN_PERLED)
        pkt[0] = RPT_PERLED
        pkt[1], pkt[2], pkt[3], pkt[4] = hdr
        off = 5
        for i in range(NUM_PER_LED):
            if i < len(colors):
                r, g, b = colors[i]
            else:
                r = g = b = 0
            pkt[off] = r & 0xFF
            pkt[off + 1] = g & 0xFF
            pkt[off + 2] = b & 0xFF
            off += 3
        buf = ctypes.create_string_buffer(bytes(pkt), LEN_PERLED)
        if not hid.HidD_SetFeature(self.handle, buf, LEN_PERLED):
            raise RuntimeError(f"写 0x53 失败（错误码 {ctypes.get_last_error()}）")
        return True

    # ---------- 0x52 区域配置的读写 ----------

    def zone_record(self, zone):
        return ZONE_OFFSET[zone]

    def get_zone(self, zone):
        o = self.zone_record(zone)
        rec = self.data[o:o + 11]
        if zone in CORSAIR_LIKE:
            return {"effect": rec[0], "color": (rec[1], rec[2], rec[3]),
                    "flags": rec[4], "color2": (rec[5], rec[6], rec[7]),
                    "extra": rec[10]}
        sbf = rec[4]
        return {
            "effect": rec[0],
            "color": (rec[1], rec[2], rec[3]),
            "speed": sbf & 0x03,
            "brightness": (sbf >> 2) & 0x1F,
            "sync_jrgb": bool(sbf & SYNC_FLAG_JRGB),
            "color2": (rec[5], rec[6], rec[7]),
            "colorFlags": rec[8],
            "extra": rec[10] if zone in (J_RAINBOW_1, J_RAINBOW_2, J_RAINBOW_3) else None,
        }

    def set_zone_static(self, zone, rgb, brightness=100):
        """用 0x52 区域路径设静态色（适合 4 针 JRGB 口，也适合整条 ARGB 单色）"""
        o = self.zone_record(zone)
        self.data[o] = MODE_STATIC
        self.data[o + 1], self.data[o + 2], self.data[o + 3] = rgb
        if zone in CORSAIR_LIKE:
            self.data[o + 4] = (brightness_level(brightness) << 2)
            self.data[o + 10] = 0
        else:
            self.data[o + 4] = (brightness_level(brightness) << 2) | (
                SYNC_FLAG_JRGB if zone in (J_RGB_1, J_RGB_2) else 0)
            self.data[o + 8] = COLOR_FLAG_USE_CUSTOM

    def set_zone_off(self, zone):
        o = self.zone_record(zone)
        self.data[o] = MODE_DISABLE
        self.data[o + 1] = self.data[o + 2] = self.data[o + 3] = 0

    def set_zone_effect(self, zone, effect, color1=(255, 0, 0), color2=None,
                        speed="medium", brightness=100, cycle=None):
        """
        用 0x52 区域路径给一个灯区设「内置效果」——效果由控制器自己跑，
        PC 端可以完全退出（这是相对每灯直控的最大好处）。
        color1/color2: 该效果用到的两个颜色（彩虹类效果忽略它们）
        speed        : low / medium / high
        brightness   : 0-100
        cycle        : 彩虹类效果的循环数（RainbowZoneData 独有字段，不传则不动）
        """
        o = self.zone_record(zone)
        self.data[o] = effect
        self.data[o + 1], self.data[o + 2], self.data[o + 3] = color1
        if color2 is not None:
            self.data[o + 5], self.data[o + 6], self.data[o + 7] = color2
        sp = SPEEDS.get(str(speed).lower(), 1)
        br = brightness_level(brightness) & 0x1F
        if zone in CORSAIR_LIKE:
            self.data[o + 4] = br << 2
            self.data[o + 5] = 0                    # corsair_quantity
            self.data[o + 10] = 0                   # is_individual
        else:
            self.data[o + 4] = (br << 2) | (sp & 0x03) | (
                SYNC_FLAG_JRGB if zone in (J_RGB_1, J_RGB_2) else 0)
            self.data[o + 8] = COLOR_FLAG_USE_CUSTOM
            if cycle is not None and zone in (J_RAINBOW_1, J_RAINBOW_2, J_RAINBOW_3):
                self.data[o + 10] = cycle

    def commit_zone(self, save=False):
        self.data[SAVE_OFFSET] = 1 if save else 0
        self.send_zone()

    # ---------- 直控（每灯）模式 ----------

    def build_enable_perled(self, leds1, leds2, leds3=None):
        """
        构造「切换到直控模式」的 0x52 报文。
        返回 (报文, sync_mode)
          sync_mode=True : 全部灯组塞进同一个 0x53 包（hdr1=6）
          sync_mode=False: 每条 ARGB 口单独发包
        """
        p = bytearray(LEN_ZONE)
        p[0] = RPT_ZONE

        def rec(zone, size):
            return ZONE_OFFSET[zone], size

        # 固定字段（照抄 OpenRGB 构造函数里的取值）
        fixed = {
            J_RGB_1: (0x08, 0x80, None),
            J_PIPE_1: (0x2A, 0x80, None),
            J_PIPE_2: (0x2A, 0x80, None),
            J_RAINBOW_1: (0x29, 0x80, 0x28),
            J_RAINBOW_2: (0x29, 0x80, 0x28),
            J_CORSAIR_OUTERLL120: (0x28, 0x80, None),
            J_RGB_2: (0x2A, 0x80, None),
        }
        for z, (sbf, cf, extra) in fixed.items():
            o = ZONE_OFFSET[z]
            p[o + 4] = sbf
            p[o + 8] = cf
            if extra is not None:
                p[o + 10] = extra
        # 板载 LED 1..9 的固定字段
        for k in range(1, 10):
            o = ZONE_OFFSET[ON_BOARD_LED_0 + k]
            p[o + 4] = 0x28
            p[o + 8] = 0x80
        # JCORSAIR 的字段排布不同
        o = ZONE_OFFSET[J_CORSAIR]
        p[o + 4] = 0x29      # fan_flags
        p[o + 5] = 0x00      # corsair_quantity
        p[o + 8] = 0x82      # padding[2]
        p[o + 10] = 0x78     # is_individual

        # 板载 LED 作为直控主控
        o = ZONE_OFFSET[ON_BOARD_LED_0]
        p[o] = MSI_DIRECT_MODE
        p[o + 4] = 0x29 | SYNC_FLAG_JRGB

        led3 = leds3 if leds3 is not None else leds2

        sync_mode = (leds1 <= SYNC_JRAINBOW_LEDS and leds2 <= SYNC_JRAINBOW_LEDS
                     and led3 <= SYNC_CORSAIR_LEDS)

        # PER_LED_BASIC_SYNC_MODE = 0x80|0x01|0x10|0x20 = 0xB1
        # PER_LED_FULL_SYNC_MODE  = 0xB1|0x02|0x04|0x08 = 0xBF
        basic = COLOR_FLAG_USE_CUSTOM | 0x01 | 0x10 | 0x20
        full = basic | 0x02 | 0x04 | 0x08

        if sync_mode:
            o = ZONE_OFFSET[J_RAINBOW_1]
            p[o] = MODE_STATIC
            p[o + 10] = SYNC_JRAINBOW_LEDS
            o = ZONE_OFFSET[J_RAINBOW_2]
            p[o] = MODE_STATIC
            p[o + 10] = SYNC_JRAINBOW_LEDS
            o = ZONE_OFFSET[J_CORSAIR]
            p[o] = MODE_STATIC
            p[o + 10] = SYNC_CORSAIR_LEDS
            p[ZONE_OFFSET[ON_BOARD_LED_0] + 8] = full
        else:
            o = ZONE_OFFSET[J_RAINBOW_1]
            p[o] = MSI_DIRECT_MODE
            p[o + 10] = 200        # JRAINBOW1_MAX_LED_COUNT
            o = ZONE_OFFSET[J_RAINBOW_2]
            p[o] = MSI_DIRECT_MODE
            p[o + 10] = 240        # JRAINBOW2_MAX_LED_COUNT
            o = ZONE_OFFSET[J_CORSAIR]
            p[o] = MSI_DIRECT_MODE
            p[o + 10] = 240        # JCORSAIR_MAX_LED_COUNT
            p[ZONE_OFFSET[ON_BOARD_LED_0] + 8] = basic

        p[SAVE_OFFSET] = 0
        return p, sync_mode

    def sync_buffer_offsets(self):
        """
        同步直控包里各灯组的起始下标（照抄 OpenRGB 构造函数的指针运算）。
        布局：板载 → JPIPE1 → JPIPE2 → JRGB们 → JARGB1(40) → JARGB2(40) → CORSAIR(120)
        """
        onboard = 0
        pipe1 = onboard + CFG_ONBOARD_LEDS
        pipe2 = pipe1 + CFG_PIPE1_LEDS
        jrgb = pipe2 + CFG_PIPE2_LEDS
        rain1 = jrgb + CFG_JRGB_COUNT
        rain2 = rain1 + SYNC_JRAINBOW_LEDS
        corsair = rain2 + SYNC_JRAINBOW_LEDS
        return {"onboard": onboard, "pipe1": pipe1, "pipe2": pipe2,
                "jrgb": jrgb, "jrainbow1": rain1, "jrainbow2": rain2,
                "jcorsair": corsair}

    def enter_direct_mode(self, leds1, leds2, leds3=0):
        """
        发送 0x52「使能报文」把控制器切到直控模式，返回 sync_mode。
        注意：该报文会把 JRGB 区域的 effect 清零 —— 进入直控后 JRGB 默认是熄灭的。
        """
        en, sync_mode = self.build_enable_perled(leds1, leds2, leds3)
        self.send_zone(en)
        time.sleep(0.013)
        return sync_mode

    def push_perled(self, colors1, colors2, colors3=None, jrgb=None, sync_mode=True):
        """
        只发 0x53 每灯数据包（须先 enter_direct_mode）。
        动画循环每帧调它即可，不必重复发使能报文。
        """
        if sync_mode:
            offs = self.sync_buffer_offsets()
            buf = [None] * NUM_PER_LED
            for i in range(CFG_JRGB_COUNT):
                buf[offs["jrgb"] + i] = (0, 0, 0)
            if jrgb:
                for i, c in enumerate(jrgb[:CFG_JRGB_COUNT]):
                    buf[offs["jrgb"] + i] = c
            if colors1:
                for i, c in enumerate(colors1[:SYNC_JRAINBOW_LEDS]):
                    buf[offs["jrainbow1"] + i] = c
            if colors2:
                for i, c in enumerate(colors2[:SYNC_JRAINBOW_LEDS]):
                    buf[offs["jrainbow2"] + i] = c
            if colors3:
                for i, c in enumerate(colors3[:SYNC_CORSAIR_LEDS]):
                    buf[offs["jcorsair"] + i] = c
            self.send_perled(PERLED_HDR["onboard_sync"],
                             [c if c else (0, 0, 0) for c in buf])
        else:
            if colors1:
                self.send_perled(PERLED_HDR["jrainbow1"], colors1)
                time.sleep(0.013)
            if colors2:
                self.send_perled(PERLED_HDR["jrainbow2"], colors2)
                time.sleep(0.013)
            if colors3:
                self.send_perled(PERLED_HDR["jcorsair"], colors3)
                time.sleep(0.013)
            self.send_perled(PERLED_HDR["onboard_sync"],
                             list(jrgb[:CFG_JRGB_COUNT]) if jrgb else [])

    def apply_argb(self, colors1, colors2, colors3=None, save=False, jrgb=None):
        """
        一次性：进入直控模式并把各 ARGB 口刷成给定颜色序列。
        colors*: (r,g,b) 列表，长度 = 该口灯珠数；传 None 表示不动该口。
        jrgb    : JRGB1/JRGB2 的整口颜色列表（4 针 12V 口各 1 颗）；None = 该口置黑。
        需要连续动画请改用 enter_direct_mode() + push_perled()。
        """
        leds1 = len(colors1) if colors1 else 0
        leds2 = len(colors2) if colors2 else 0
        leds3 = len(colors3) if colors3 else 0
        sync_mode = self.enter_direct_mode(leds1, leds2, leds3)
        self.push_perled(colors1, colors2, colors3, jrgb, sync_mode)
        return sync_mode

    def apply_jrgb(self, rgb1, rgb2=None, brightness=100, save=False):
        """4 针 12V JRGB 口（整口一个颜色）。直控模式下它们也在 0x53 包里。"""
        colors = []
        if rgb1:
            colors.append(rgb1)
        if rgb2:
            colors.append(rgb2)
        if not colors:
            return
        en, sync_mode = self.build_enable_perled(0, 0, 0)
        self.send_zone(en)
        time.sleep(0.013)
        if sync_mode:
            offs = self.sync_buffer_offsets()
            buf = [(0, 0, 0)] * NUM_PER_LED
            for i, c in enumerate(colors[:CFG_JRGB_COUNT]):
                buf[offs["jrgb"] + i] = c
            self.send_perled(PERLED_HDR["onboard_sync"], buf)
        else:
            self.send_perled(PERLED_HDR["onboard_sync"], colors)

    def all_off(self, save=False):
        """所有灯区关闭，并退出直控模式回到普通模式"""
        self.read_zone()
        for z in list(ZONE_OFFSET.keys()):
            self.set_zone_off(z)
        self.commit_zone(save)


# ─────────────────────────── 动画 ───────────────────────────

def run_rainbow_breath(dev, leds1, leds2, fps=20.0,
                       hue_cycle=8.0, breath_cycle=4.0, min_level=0.12):
    """
    彩虹呼吸：色相整体随时间流动，亮度按正弦在 min_level..1.0 之间起伏。
    只驱动 ARGB 两口，JRGB 全程保持熄灭。Ctrl+C 退出并熄灯。
    """
    interval = 1.0 / fps
    sync_mode = dev.enter_direct_mode(leds1, leds2, 0)
    print(f"彩虹呼吸：ARGB1 {leds1} 颗 + ARGB2 {leds2} 颗  @ {fps:.0f} FPS，JRGB 不亮")
    print("Ctrl+C 退出\n")
    try:
        t0 = time.time()
        while True:
            t = time.time() - t0
            breath = min_level + (1.0 - min_level) * (
                0.5 + 0.5 * math.sin(2 * math.pi * t / breath_cycle))
            shift = (t / hue_cycle) % 1.0
            dev.push_perled(rainbow_colors(leds1, shift, 1.0, breath),
                            rainbow_colors(leds2, shift, 1.0, breath),
                            None, None, sync_mode)
            time.sleep(interval)
    except KeyboardInterrupt:
        dev.push_perled([(0, 0, 0)] * leds1, [(0, 0, 0)] * leds2,
                        None, None, sync_mode)
        print("\n退出，熄灯。")


# ─────────────────────────── 展示 ───────────────────────────

def hexdump(data, n=32):
    return " ".join(f"{x:02X}" for x in bytes(data[:n]))


def cmd_diag(dev):
    print("=" * 66)
    print("MSI Mystic Light 诊断")
    print("=" * 66)
    print(f"设备      : {dev.product or '(无产品名)'}")
    print(f"路径      : {dev.path[:88]}")
    print(f"Feature   : 最大 {dev.feature_len} 字节  "
          f"(0x52=185 / 0x53=725 -> 185 协议 + 每灯直控)")
    print()

    dev.read_zone()
    print("当前各灯区状态（读自 0x52）：")
    print(f"  {'灯区':<14}{'效果':<28}{'颜色':<18}{'亮度':<7}备注")
    for z in sorted(ZONE_OFFSET.keys(), key=lambda k: ZONE_OFFSET[k]):
        info = dev.get_zone(z)
        name = ZONE_NAME.get(z, str(z))
        eff = info["effect"]
        if eff == MSI_DIRECT_MODE:
            eff_name, note = "直控", "← 每灯直控模式"
        else:
            eff_name, note = MODE_NAME.get(eff, f"0x{eff:02X}"), ""
        if info.get("extra"):
            note = (note + f" cycle={info['extra']}").strip()
        c = info["color"]
        br = info.get("brightness")
        br = f"{br * 10}%" if br is not None else "-"
        print(f"  {name:<14}{eff_name:<28}RGB{str(c):<15}{br:<7}{note}")

    print()
    print("支持的灯区（本板 0x0076 通用配置）:")
    for z in (J_RGB_1, J_RGB_2, J_RAINBOW_1, J_RAINBOW_2):
        print(f"  {ZONE_NAME[z]:<10} 类型 {'4针12V JRGB' if z in (J_RGB_1, J_RGB_2) else '3针 ARGB'}")


def cmd_list():
    print("可用灯区名（用于 --zone）：")
    for n, z in sorted(NAME_TO_ZONE.items()):
        if n.startswith("j") or n.startswith("a"):
            print(f"  {n:<12} -> {ZONE_NAME.get(z, z)}")
    print()
    print("示例：python mystic.py --zone jrgb1 --color FF0000")


# 效果按「看起来像什么」分组，方便挑
EFFECT_GROUPS = [
    ("基础 / 单色", ["disable", "static", "breathing", "flashing",
                     "double flashing", "lightning", "blink"]),
    ("流动 / 扫描", ["msi marquee", "marquee", "meteor", "double meteor",
                     "water drop", "color wave", "color shift", "stack",
                     "energy", "visor", "movie"]),
    ("彩虹 / 流光（控制器自动配色，不用给颜色）",
     ["rainbow", "rainbow wave", "jrainbow", "msi rainbow",
      "rainbow flashing", "rainbow double flashing"]),
    ("脉动 / 光环", ["color pulse", "color ring", "color ring flashing",
                     "color ring double flashing", "planetary", "random",
                     "fire", "lava"]),
    ("音乐律动（需主板带音频输入，多数板无效）", ["jazz", "rap", "pop", "play"]),
    ("其它", ["clock", "fan control", "disable2", "corsair que"]),
]


def cmd_list_effects():
    print("MSI Mystic Light 内置效果（0x52 区域路径）")
    print("效果跑在控制器里 —— 脚本退出、甚至关机后重新上电，都还在。")
    print()
    for title, keys in EFFECT_GROUPS:
        print(f"[{title}]")
        for k in keys:
            if k in MODES:
                val, desc = MODES[k]
                print(f"  0x{val:02X}  {k:<28}{desc}")
        print()
    print("参数：--speed low|medium|high    --brightness 0-100")
    print("示例：python mystic.py --effect \"rainbow wave\" --speed high --brightness 80")


def main():
    ap = argparse.ArgumentParser(
        description="微星 Mystic Light 主板灯控（Python 直连，不需要 MSI Center）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  python mystic.py                           不带参数 → 控制器内置「rainbow wave」（PC 可退出）
  python mystic.py --diag                    只看当前状态，不改灯
  python mystic.py --list                    列出灯区名
  python mystic.py --argb1 FF0000 --leds1 6   1号 ARGB 口全红（本机 6 颗）
  python mystic.py --argb1 FF0000 --argb2 00FF00            两口分别上色（6/12）
  python mystic.py --effect "rainbow wave"   同上，显式指定内置效果
  python mystic.py --effect breathing --speed low --brightness 50
  python mystic.py --list-effects            列出控制器自带的全部效果
  python mystic.py --rainbow-breath          PC 逐帧推的彩虹呼吸（要开着脚本，Ctrl+C 退出）
  python mystic.py --rainbow1 --leds1 6      1 号口静态彩虹渐变（PC 逐帧推）
  python mystic.py --jrgb FF0000             4 针 JRGB 口静态红（整口单色）
  python mystic.py --off                     全部关灯，并退出直控模式
""")
    ap.add_argument("--diag", action="store_true", help="诊断：读设备与当前灯区状态，不改灯")
    ap.add_argument("--list", action="store_true", help="列出灯区名")

    ap.add_argument("--argb1", metavar="RRGGBB", help="1 号 3 针 ARGB 口颜色")
    ap.add_argument("--argb2", metavar="RRGGBB", help="2 号 3 针 ARGB 口颜色")
    ap.add_argument("--argb3", metavar="RRGGBB", help="3 号 3 针 ARGB 口颜色（部分板有）")
    ap.add_argument("--both", metavar="RRGGBB", help="两个 ARGB 口同色")
    ap.add_argument("--leds1", type=int, default=6, help="1 号 ARGB 口灯珠数（本机 6）")
    ap.add_argument("--leds2", type=int, default=12, help="2 号 ARGB 口灯珠数（本机 12）")
    ap.add_argument("--leds3", type=int, default=4, help="3 号 ARGB 口灯珠数（本机无此口）")
    ap.add_argument("--leds", type=int, help="把上面三条统一设成同一个数（本机两口颗数不同，慎用）")
    ap.add_argument("--rainbow1", action="store_true", help="1 号口彩虹渐变（每颗一色，PC 逐帧推）")
    ap.add_argument("--rainbow-breath", action="store_true",
                    help="PC 逐帧推的彩虹呼吸动画（脚本必须一直开着；"
                         "不带参数时的默认行为是控制器内置的 rainbow wave）")

    ap.add_argument("--effect", metavar="NAME",
                    help="用控制器内置效果驱动 ARGB 口（见 --list-effects）")
    ap.add_argument("--speed", default="medium", choices=["low", "medium", "high"],
                    help="--effect 的速度（默认 medium）")
    ap.add_argument("--color1", metavar="RRGGBB", help="配合 --effect：主色（默认 FF0000）")
    ap.add_argument("--color2", metavar="RRGGBB", help="配合 --effect：辅色（默认同主色）")
    ap.add_argument("--list-effects", action="store_true", help="列出控制器支持的全部内置效果")

    ap.add_argument("--jrgb", metavar="RRGGBB", help="JRGB1（4 针）颜色")
    ap.add_argument("--jrgb2", metavar="RRGGBB", help="JRGB2（4 针）颜色")
    ap.add_argument("--zone", help="配合 --color 使用：指定单个灯区（见 --list）")
    ap.add_argument("--color", metavar="RRGGBB", help="配合 --zone：该灯区静态色")
    ap.add_argument("--brightness", type=int, default=100, help="静态色亮度 0-100（默认 100）")

    ap.add_argument("--off", action="store_true", help="全部关灯并退出直控模式")
    ap.add_argument("--save", action="store_true",
                    help="写进控制器 flash（重启仍生效）—— 默认只在内存生效")

    args = ap.parse_args()

    if args.list:
        cmd_list()
        return

    if args.list_effects:
        cmd_list_effects()
        return

    try:
        dev = MysticLight185().open()
    except RuntimeError as e:
        print(f"错误：{e}")
        return 1

    try:
        if args.diag:
            cmd_diag(dev)
            return

        if args.off:
            dev.all_off(save=args.save)
            print("已关闭全部灯区，并退出直控模式。")
            return

        if args.effect:
            key = resolve_effect(args.effect)
            if key is None:
                print(f"未知效果 {args.effect!r}，用 --list-effects 看可用名字")
                return 1
            eff, desc = MODES[key]
            c1 = parse_color(args.color1) if args.color1 else (255, 0, 0)
            c2 = parse_color(args.color2) if args.color2 else c1
            if args.zone:
                z = NAME_TO_ZONE.get(args.zone.lower())
                if z is None:
                    print(f"未知灯区 {args.zone!r}，用 --list 看可用名字")
                    return 1
                targets = [z]
            else:
                targets = [J_RAINBOW_1, J_RAINBOW_2]
            dev.read_zone()
            for z in targets:
                dev.set_zone_effect(z, eff, c1, c2, args.speed, args.brightness)
            dev.commit_zone(save=args.save)
            names = "、".join(ZONE_NAME.get(z, str(z)) for z in targets)
            print(f"内置效果 「{key}」(0x{eff:02X} {desc}) → {names}")
            print(f"  速度 {args.speed}   亮度 {args.brightness}%"
                  + ("" if eff in RAINBOW_LIKE else f"   颜色 {c1} / {c2}"))
            if eff in RAINBOW_LIKE:
                print("  （该效果配色由控制器自动生成，--color1/--color2 不生效）")
            print("效果跑在控制器里，脚本可以立刻退出；JRGB 未改动。")
            if not args.save:
                print("当前只在控制器内存生效（重启恢复）；要持久化加 --save。")
                print("注意：MSI Center 若在运行会覆盖掉。")
            return

        if args.zone and args.color:
            z = NAME_TO_ZONE.get(args.zone.lower())
            if z is None:
                print(f"未知灯区 {args.zone!r}，用 --list 看可用名字")
                return 1
            rgb = parse_color(args.color)
            dev.read_zone()
            dev.set_zone_static(z, rgb, args.brightness)
            dev.commit_zone(save=args.save)
            print(f"{ZONE_NAME.get(z, z)} -> RGB{rgb}  亮度 {args.brightness}%")
            return

        if args.leds:
            args.leds1 = args.leds2 = args.leds3 = args.leds

        if args.jrgb or args.jrgb2:
            rgb1 = parse_color(args.jrgb) if args.jrgb else None
            rgb2 = parse_color(args.jrgb2) if args.jrgb2 else None
            dev.apply_jrgb(rgb1, rgb2, args.brightness)
            print(f"JRGB 静态色：{rgb1} {rgb2 or ''}")

        c1 = c2 = c3 = None
        if args.both:
            c1 = c2 = parse_color(args.both)
            if args.leds3:
                c3 = c1
        if args.argb1:
            c1 = parse_color(args.argb1)
        if args.argb2:
            c2 = parse_color(args.argb2)
        if args.argb3:
            c3 = parse_color(args.argb3)

        if args.rainbow1:
            c1 = rainbow_colors(args.leds1)

        if args.rainbow_breath:
            run_rainbow_breath(dev, args.leds1, args.leds2)
            return

        # 不带任何动作参数 → 默认：控制器内置的 rainbow wave
        no_action = not any([args.diag, args.list, args.list_effects, args.off,
                             args.effect, args.argb1, args.argb2,
                             args.argb3, args.both, args.rainbow1, args.jrgb,
                             args.jrgb2, args.zone])
        if no_action:
            # 用控制器内置效果，而不是 PC 逐帧推：
            #   好处是脚本退出后灯效还在（直到重启 / MSI Center 覆盖），
            #   代价是配色由控制器生成，做不出"每颗独立 + 呼吸"那种自定义动画。
            eff, desc = MODES["rainbow wave"]
            dev.read_zone()
            for z in (J_RAINBOW_1, J_RAINBOW_2):
                dev.set_zone_effect(z, eff, (255, 0, 0), None, "medium", 100)
            dev.commit_zone(save=False)
            print(f"默认 → 控制器内置「rainbow wave」(0x{eff:02X} {desc})"
                  f" 已下发到 JARGB1 + JARGB2，JRGB 未改动。")
            print("  效果跑在控制器里，本脚本可以立刻退出（Ctrl+C 也不会熄灯）。")
            print("  未写 flash：重启恢复原状；MSI Center 若在运行会覆盖掉。")
            print("  想要 PC 逐帧推的彩虹呼吸：python mystic.py --rainbow-breath")
            return

        if c1 or c2 or c3:
            def expand(c, n):
                if c is None:
                    return None
                if isinstance(c, list):
                    return c
                return [c] * n
            sync = dev.apply_argb(expand(c1, args.leds1), expand(c2, args.leds2),
                                  expand(c3, args.leds3), save=args.save)
            print(f"直控模式：{'单包合并' if sync else '每口单独发包'}"
                  f"  灯珠数 {args.leds1}/{args.leds2}"
                  + (f"/{args.leds3}" if c3 else ""))
            print("（改动只在控制器内存里，重启后恢复；要持久化加 --save）")
            return

        ap.print_help()
    finally:
        dev.close()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
