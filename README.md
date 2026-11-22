# ESP-WS2812 · 60 颗音乐电平灯带

WeMOS D1 mini + 60 颗 WS2812B。放歌时按封面配色和系统输出峰值驱动，
没播音乐时用麦克风电平表，空闲有 13 种灯效（含 GPU 监控）。

固件是 v6 二进制帧协议（逐颗独立控色，50Hz）；控制端是单进程 Python 服务，
内嵌 Web 面板。断开串口、电脑关机、主机失联都有 fail-safe 处理。

## 快速开始

```bat
:: 装依赖
py -3.15 -m pip install -r ESP-WS2812/host/requirements.txt

:: 烧录固件（先 DryRun 看一遍，确认 COM 口）
powershell -ExecutionPolicy Bypass -File ESP-WS2812/flash_d1mini.ps1 -DryRun

:: 启动控制服务，面板在 http://127.0.0.1:51876/esp60led
py -3.15 ESP-WS2812/host/led_host_60.py
```

桌面快捷方式「ESP-WS2812 灯带面板」会用 Edge 应用窗口（无地址栏）打开面板，
服务没启动时会自动拉起。

完整说明见 [ESP-WS2812/README.md](ESP-WS2812/README.md)。

## 许可证

[MIT](LICENSE) · Copyright (c) 2026 Ethan
