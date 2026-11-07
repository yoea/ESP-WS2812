#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
枚举微星 Mystic Light HID 设备声明了哪些 Feature Report（只读）。

通过 HidP_GetValueCaps 读取 HID 报告描述符的解析结果，
列出每个 Feature Report 的 ReportID 与字节长度。

据此判断板子属于哪一代协议：
  0x52 = 185 字节  +  0x53 = 761 字节   -> 185 协议（支持 ARGB 每灯独立控色）
  0x51 = 761 字节                       -> 761 协议（新一代）
  0x50 = 290 字节                       -> 290 协议（B860/X870 那类）

本脚本只读，不写任何报文。
"""

import ctypes
import sys
from ctypes import byref, wintypes

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

HID_GUID_DATA = (0x4D1E55B2, 0xF16F, 0x11CF,
                 (0x88, 0xCB, 0x00, 0x11, 0x11, 0x00, 0x00, 0x30))
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value

HIDP_STATUS_SUCCESS = 0x00110000
HIDP_STATUS_BUFFER_TOO_SMALL = 0xC0110007 - 0x100000000   # 有符号
HidP_Feature = 2


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_ulonglong)]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("DevicePath", ctypes.c_wchar * 512)]


class HIDP_RANGE(ctypes.Structure):
    _fields_ = [("UsageMin", wintypes.USHORT), ("UsageMax", wintypes.USHORT),
                ("StringMin", wintypes.USHORT), ("StringMax", wintypes.USHORT),
                ("DesignatorMin", wintypes.USHORT), ("DesignatorMax", wintypes.USHORT),
                ("DataIndexMin", wintypes.USHORT), ("DataIndexMax", wintypes.USHORT)]


class HIDP_NOTRANGE(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("Reserved1", wintypes.USHORT),
                ("StringIndex", wintypes.USHORT), ("Reserved2", wintypes.USHORT),
                ("DesignatorIndex", wintypes.USHORT), ("Reserved3", wintypes.USHORT),
                ("DataIndex", wintypes.USHORT), ("Reserved4", wintypes.USHORT)]


class HIDP_UNION(ctypes.Union):
    _fields_ = [("Range", HIDP_RANGE), ("NotRange", HIDP_NOTRANGE)]


class HIDP_VALUE_CAPS(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("UsagePage", wintypes.USHORT),
        ("ReportID", ctypes.c_ubyte),
        ("IsAlias", ctypes.c_ubyte),
        ("BitField", wintypes.USHORT),
        ("LinkCollection", wintypes.USHORT),
        ("LinkUsage", wintypes.USHORT),
        ("LinkUsagePage", wintypes.USHORT),
        ("IsRange", ctypes.c_ubyte),
        ("IsStringRange", ctypes.c_ubyte),
        ("IsDesignatorRange", ctypes.c_ubyte),
        ("IsAbsolute", ctypes.c_ubyte),
        ("HasNull", ctypes.c_ubyte),
        ("Reserved", ctypes.c_ubyte),
        ("BitSize", wintypes.USHORT),
        ("ReportCount", wintypes.USHORT),
        ("Reserved2", wintypes.USHORT * 5),
        ("UnitsExp", wintypes.ULONG),
        ("Units", wintypes.ULONG),
        ("LogicalMin", wintypes.LONG),
        ("LogicalMax", wintypes.LONG),
        ("PhysicalMin", wintypes.LONG),
        ("PhysicalMax", wintypes.LONG),
        ("u", HIDP_UNION),
    ]


hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOL
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetValueCaps.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                  ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
hid.HidP_GetValueCaps.restype = ctypes.c_long
hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetFeature.restype = wintypes.BOOL
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetProductString.restype = wintypes.BOOL

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


def parse_vidpid(path):
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


def open_msi():
    guid = GUID()
    guid.Data1, guid.Data2, guid.Data3 = HID_GUID_DATA[0], HID_GUID_DATA[1], HID_GUID_DATA[2]
    for i, v in enumerate(HID_GUID_DATA[3]):
        guid.Data4[i] = v

    hdev = setupapi.SetupDiGetClassDevsW(byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdev == INVALID_HANDLE:
        print("SetupDiGetClassDevs 失败:", ctypes.get_last_error())
        return None

    handle, idx = None, 0
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
        vid, pid = parse_vidpid(detail.DevicePath)
        if vid == 0x0DB0 and handle is None:
            h = kernel32.CreateFileW(detail.DevicePath, GENERIC_READ | GENERIC_WRITE,
                                     FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                                     OPEN_EXISTING, 0, None)
            if h != INVALID_HANDLE:
                handle = h

    setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return handle


def main():
    handle = open_msi()
    if handle is None:
        print("没找到可打开的微星(0DB0) HID 设备。请用管理员身份重跑。")
        return

    pbuf = ctypes.create_unicode_buffer(256)
    if hid.HidD_GetProductString(handle, pbuf, 512):
        print(f"设备: {pbuf.value}\n")

    pp = ctypes.c_void_p()
    if not hid.HidD_GetPreparsedData(handle, byref(pp)):
        print("HidD_GetPreparsedData 失败")
        kernel32.CloseHandle(handle)
        return

    # 第一次调用拿数量
    n = wintypes.USHORT(0)
    hid.HidP_GetValueCaps(HidP_Feature, None, byref(n), pp)
    if n.value == 0:
        print("描述符里没有 Feature Report？")
        hid.HidD_FreePreparsedData(pp)
        kernel32.CloseHandle(handle)
        return

    print(f"Feature ValueCaps 共 {n.value} 条\n")

    arr = (HIDP_VALUE_CAPS * n.value)()
    cnt = wintypes.USHORT(n.value)
    st = hid.HidP_GetValueCaps(HidP_Feature, ctypes.cast(arr, ctypes.c_void_p),
                               byref(cnt), pp)
    if (st & 0xFFFFFFFF) != HIDP_STATUS_SUCCESS:
        print(f"HidP_GetValueCaps 失败 status=0x{st & 0xFFFFFFFF:08X}")
        hid.HidD_FreePreparsedData(pp)
        kernel32.CloseHandle(handle)
        return

    # 按 ReportID 汇总位数
    reports = {}
    for i in range(cnt.value):
        c = arr[i]
        bits = c.BitSize * c.ReportCount
        rid = c.ReportID
        if rid not in reports:
            reports[rid] = {"bits": 0, "n": 0, "pages": set(), "usages": []}
        reports[rid]["bits"] += bits
        reports[rid]["n"] += 1
        reports[rid]["pages"].add(c.UsagePage)
        u = c.u.NotRange.Usage if not c.IsRange else c.u.Range.UsageMin
        reports[rid]["usages"].append((c.UsagePage, u, c.BitSize, c.ReportCount))

    print("声明的 Feature Report：")
    print(f"  {'ReportID':<10} {'字节长度':<10} {'字段数':<8}  UsagePage")
    for rid in sorted(reports):
        r = reports[rid]
        nbytes = (r["bits"] + 7) // 8 + 1     # +1 是 ReportID 本身
        pages = ",".join(f"0x{p:04X}" for p in sorted(r["pages"]))
        print(f"  0x{rid:02X}{'':<7} {nbytes:<10} {r['n']:<8}  {pages}")

    print("\n逐个尝试读取（用各 report 自身长度）：")
    for rid in sorted(reports):
        nbytes = (reports[rid]["bits"] + 7) // 8 + 1
        buf = ctypes.create_string_buffer(nbytes)
        buf[0] = bytes([rid])
        ok = hid.HidD_GetFeature(handle, buf, nbytes)
        err = ctypes.get_last_error()
        head = " ".join(f"{b:02X}" for b in buf.raw[:24])
        print(f"  0x{rid:02X} ({nbytes:4d}B): "
              f"{'成功' if ok else f'失败 err={err}'}   {head if ok else ''}")

    hid.HidD_FreePreparsedData(pp)
    kernel32.CloseHandle(handle)

    print("\n判读：")
    print("  看到 0x52≈185 且 0x53≈761  -> 185 协议（ARGB 每灯独立控色走 0x53）")
    print("  看到 0x51=761              -> 761 协议")
    print("  看到 0x50=290              -> 290 协议")


if __name__ == "__main__":
    main()
