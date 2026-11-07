#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微星 Mystic Light HID 设备只读探测。

只做三件事：找到 0DB0:0076 设备、打开它、读几个 Feature Report。
【不会改变任何灯效】，纯读取，用来判断控制器属于哪种协议版本。

关键指标是 FeatureReportByteLength：
  761 -> 761 控制器（JARGB 每灯独立控色，新主板）
  290 -> 0x50 报文（板载区域 + 灯效）
  185 -> 185 控制器（区域配置，OpenRGB 用的那种）
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

# GUID_DEVINTERFACE_HID = {4D1E55B2-F16F-11CF-88CB-001111000030}
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


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_ulonglong)]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("DevicePath", ctypes.c_wchar * 512)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]


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


hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = wintypes.BOOL
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wintypes.BOOL
# 注意是 HidP_(HID Parser) 不是 HidD_(HID Device)
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = wintypes.ULONG
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetFeature.restype = wintypes.BOOL
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetProductString.restype = wintypes.BOOL
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE

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


def hexdump(data, n=32):
    b = bytes(data[:n])
    return " ".join(f"{x:02X}" for x in b)


def parse_vidpid(path):
    """从设备接口路径里抠出 VID/PID，例如 ...\\vid_0db0&pid_0076#..."""
    low = path.lower()
    vid = pid = None
    i = low.find("vid_")
    if i >= 0:
        try:
            vid = int(low[i + 4:i + 8], 16)
        except ValueError:
            pass
    j = low.find("pid_")
    if j >= 0:
        try:
            pid = int(low[j + 4:j + 8], 16)
        except ValueError:
            pass
    return vid, pid


def enum_hid_paths():
    """枚举所有 HID 接口路径（不需要打开设备，沙箱/权限受限也能跑）"""
    guid = GUID()
    guid.Data1, guid.Data2, guid.Data3 = HID_GUID_DATA[0], HID_GUID_DATA[1], HID_GUID_DATA[2]
    for i, v in enumerate(HID_GUID_DATA[3]):
        guid.Data4[i] = v

    hdev = setupapi.SetupDiGetClassDevsW(byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if hdev == INVALID_HANDLE:
        print("SetupDiGetClassDevs 失败:", ctypes.get_last_error())
        return []

    paths, idx = [], 0
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
                hdev, byref(iface), byref(detail),
                ctypes.sizeof(detail), None, None):
            continue
        paths.append(detail.DevicePath)

    setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return paths


def main():
    paths = enum_hid_paths()
    if not paths:
        return

    # 先按路径分类，再尝试打开（打开会因权限失败，但不影响识别 VID/PID）
    found = []          # (vid, pid, path, handle)  handle 可能为 None
    for path in paths:
        vid, pid = parse_vidpid(path)
        if vid is None or pid is None:
            continue
        handle = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE,
                                      FILE_SHARE_READ | FILE_SHARE_WRITE,
                                      None, OPEN_EXISTING, 0, None)
        if handle == INVALID_HANDLE:
            handle = None
            err = ctypes.get_last_error()
        else:
            err = 0
        found.append((vid, pid, path, handle, err))

    msi = [f for f in found if f[0] == 0x0DB0]
    opened = [f for f in found if f[3] is not None]

    print(f"枚举到 HID 接口 {len(paths)} 个，其中可识别 VID/PID 的 {len(found)} 个，"
          f"能打开的 {len(opened)} 个。\n")

    if not msi:
        print("没找到微星(VID_0DB0)的 HID 接口。")
    else:
        print(f"微星(0DB0)设备 {len(msi)} 个：")
        for vid, pid, path, handle, err in msi:
            state = "可打开" if handle is not None else f"打不开(err={err})"
            print(f"  VID_{vid:04X} PID_{pid:04X}  {state}")
            print(f"      {path[:100]}")

    target = next((f for f in msi if f[3] is not None), None)
    if target is None:
        if msi:
            print("\n微星设备存在但无法打开句柄 —— 请用【管理员身份】重跑本脚本。")
        for f in found:
            if f[3] is not None:
                kernel32.CloseHandle(f[3])
        return

    vid, pid, path, handle, _ = target
    print(f"\n目标设备: VID_{vid:04X} PID_{pid:04X}")


    print(f"  路径: {path[:90]}")

    # 产品名
    pbuf = ctypes.create_unicode_buffer(256)
    if hid.HidD_GetProductString(handle, pbuf, 512):
        print(f"  产品名: {pbuf.value}")

    # 能力：Feature 报文最大长度决定协议版本
    pp = ctypes.c_void_p()
    if hid.HidD_GetPreparsedData(handle, byref(pp)):
        caps = HIDP_CAPS()
        if hid.HidP_GetCaps(pp, byref(caps)) == 0x110000:   # HIDP_STATUS_SUCCESS
            print("\n  报文长度：")
            print(f"    Feature {caps.FeatureReportByteLength} 字节")
            print(f"    Input   {caps.InputReportByteLength} 字节")
            print(f"    Output  {caps.OutputReportByteLength} 字节")
            fb = caps.FeatureReportByteLength
            if fb >= 761:
                print("    -> 761 控制器：支持 JARGB 每灯独立控色（Report 0x51）")
            elif fb >= 290:
                print("    -> 290 字节：0x50 报文（板载区域 + 灯效）")
            elif fb >= 185:
                print("    -> 185 控制器：区域配置（Report 0x52）")
            else:
                print("    -> 长度偏小，可能不是灯控接口")
        else:
            print("  HidP_GetCaps 失败")
        hid.HidD_FreePreparsedData(pp)

    # 只读几个 feature report，看响应（不改灯效）
    print("\n  读取 Feature Report（只读，不会改灯）：")
    for rid, size in ((0x52, 185), (0x50, 290), (0x51, 761)):
        buf = ctypes.create_string_buffer(size)
        buf[0] = rid
        ok = hid.HidD_GetFeature(handle, buf, size)
        err = ctypes.get_last_error()
        print(f"    Report 0x{rid:02X} 长度{size:4d}: {'成功' if ok else f'失败(错误码 {err})'}")
        if ok:
            print(f"        前32字节: {hexdump(buf.raw)}")

    kernel32.CloseHandle(handle)
    print("\n提示：如果全部读取都失败，多半是权限问题——请用管理员身份重跑本脚本。")


if __name__ == "__main__":
    main()
