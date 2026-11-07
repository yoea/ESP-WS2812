#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主板灯控设备检测。

用 SetupAPI 枚举系统里所有存在的设备，读出描述、硬件 ID、驱动服务名，
再按灯控相关关键字筛选。零第三方依赖（ctypes 直调 setupapi.dll）。

重点看两类：
  1) USB HID 灯控设备 —— 硬件 ID 形如 USB\VID_0DB0&PID_xxxx（0DB0 = 微星），
     这类可以直接用 hidapi 读写，Python 完全能控。
  2) SuperIO / SMBus 芯片（Nuvoton、ITE、Winbond）—— 走 IO 端口，
     需要内核级驱动（如 WinRing0 / inpout32）才能访问，Python 要走弯路。
"""

import ctypes
import sys
from ctypes import byref, wintypes

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)

DIGCF_ALLCLASSES = 0x04
DIGCF_PRESENT = 0x02
SPDRP_DEVICEDESC = 0x00000000
SPDRP_HARDWAREID = 0x00000001
SPDRP_SERVICE = 0x00000004
SPDRP_CLASS = 0x00000007
SPDRP_MFG = 0x0000000B
SPDRP_FRIENDLYNAME = 0x0000000C
INVALID_HANDLE = ctypes.c_void_p(-1).value


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("ClassGuid", GUID),
                ("DevInst", wintypes.DWORD), ("Reserved", ctypes.c_ulonglong)]


setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                          wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiEnumDeviceInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                           ctypes.POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD)]
setupapi.SetupDiGetDeviceRegistryPropertyW.restype = wintypes.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]


def get_prop(h, dev, prop):
    size = wintypes.DWORD(0)
    ptype = wintypes.DWORD(0)
    setupapi.SetupDiGetDeviceRegistryPropertyW(h, byref(dev), prop, byref(ptype),
                                               None, 0, byref(size))
    if size.value == 0:
        return None
    raw = ctypes.create_string_buffer(size.value)
    if not setupapi.SetupDiGetDeviceRegistryPropertyW(
            h, byref(dev), prop, byref(ptype), raw, size, byref(size)):
        return None
    text = raw.raw.decode("utf-16-le", errors="ignore")
    parts = [p for p in text.split("\x00") if p]
    return parts[0] if len(parts) == 1 else parts


# 注意别用 "ene" 这种短关键字：会匹配到 "GENERIC"，刷出一堆无关设备
KEYWORDS = ("msi", "micro-star", "mystic", "0db0", "led", "rgb", "lighting",
            "nuvoton", "winbond", "superio", "smbus", "corsair", "nzxt")


def main():
    h = setupapi.SetupDiGetClassDevsW(None, None, None,
                                      DIGCF_ALLCLASSES | DIGCF_PRESENT)
    if h == INVALID_HANDLE:
        print("SetupDiGetClassDevs 失败:", ctypes.get_last_error())
        return

    hits, total = [], 0
    usb_hid, seen_tags = [], set()
    idx = 0
    while True:
        dev = SP_DEVINFO_DATA()
        dev.cbSize = ctypes.sizeof(SP_DEVINFO_DATA)
        if not setupapi.SetupDiEnumDeviceInfo(h, idx, byref(dev)):
            break
        idx += 1
        total += 1

        desc = get_prop(h, dev, SPDRP_DEVICEDESC) or ""
        hwids = get_prop(h, dev, SPDRP_HARDWAREID) or []
        if isinstance(hwids, str):
            hwids = [hwids]
        svc = get_prop(h, dev, SPDRP_SERVICE) or ""
        mfg = get_prop(h, dev, SPDRP_MFG) or ""

        blob = " ".join([desc, mfg, svc] + list(hwids)).lower()
        if any(k in blob for k in KEYWORDS):
            hits.append((desc, mfg, svc, hwids))

        # 顺带汇总所有 USB / HID 设备的 VID&PID，便于人工核对
        for hid_str in hwids:
            low = hid_str.lower()
            tag = None
            if "\\vid_" in low:
                bus = low.split("\\")[0]
                if bus in ("usb", "hid"):
                    vid = low.split("vid_")[1][:4]
                    pid = low.split("pid_")[1][:4] if "pid_" in low else "????"
                    tag = (bus, vid, pid)
            if tag and tag not in seen_tags:
                seen_tags.add(tag)
                usb_hid.append((tag, desc))

    setupapi.SetupDiDestroyDeviceInfoList(h)

    print(f"扫描到 {total} 个设备，其中灯控/厂商相关 {len(hits)} 个：\n")
    for desc, mfg, svc, hwids in hits:
        print(f"● {desc}")
        if mfg:
            print(f"    厂商  : {mfg}")
        if svc:
            print(f"    驱动服务: {svc}")
        for i in hwids[:4]:
            print(f"    硬件ID: {i}")
        print()

    print("=" * 62)
    print("全部 USB / HID 设备的 VID&PID：\n")
    msi_vids = ("0db0",)
    for (bus, vid, pid), desc in sorted(usb_hid):
        mark = "  <<< 微星" if vid in msi_vids else ""
        name = desc[:34]
        print(f"  {bus.upper():<4} VID_{vid.upper()} PID_{pid.upper()}   {name}{mark}")

    print()
    print("=" * 62)
    print("判定要点：")
    print("  - 看到  USB\\VID_0DB0...  -> 微星 USB HID 灯控，Python 可直接控")
    print("  - 只看到 Nuvoton/ITE/Winbond SuperIO -> 走 IO 端口，需内核驱动")
    print("  - 两者都没出现 -> 灯控可能在显卡/内存条上，不归主板管")


if __name__ == "__main__":
    main()
