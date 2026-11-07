@echo off
chcp 936 >nul
title CH340 驱动锁定工具

rem 检查管理员权限, 没有就自动提权重启本脚本
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在请求管理员权限...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo === CH340 驱动锁定工具 (修复 3.9 驱动被强推问题) ===
echo.

pushd "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0ch340-fix.ps1"
popd

echo.
pause
