<#
  CH340 / CH341 串口驱动锁定工具  (WeMOS D1 mini)
  ------------------------------------------------------------
  作用:
    1) 从驱动存储(Driver Store)里删掉 Windows 更新强推的 CH340 3.9 驱动包
    2) 保留 3.5 驱动包
    3) 写入策略, 禁止 Windows 更新 / PnP 再去拉驱动回来
  之后如果哪天又被顶掉了, 再跑一次本脚本即可。

  用法: 双击 ch340-fix.bat  或  右键本文件 -> 使用 PowerShell 运行(管理员)
#>

param(
    [string]$KeepVersion = '3.5'
)

$ErrorActionPreference = 'Continue'
try { $Host.UI.RawUI.WindowTitle = 'CH340 驱动锁定工具' } catch {}

function Test-Administrator {
    $u = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($u)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Section($t) {
    Write-Host ''
    Write-Host ('=== ' + $t + ' ===') -ForegroundColor Cyan
}

if (-not (Test-Administrator)) {
    Write-Host '当前不是管理员权限, 请右键以管理员身份运行。' -ForegroundColor Red
    Read-Host '按回车退出' | Out-Null
    exit 1
}

# ---------------------------------------------------------------
# 1. 扫描驱动存储, 解析 pnputil 输出(兼容中英文系统)
# ---------------------------------------------------------------
Write-Section '扫描驱动存储中的 CH34x 驱动包'

$raw = & pnputil.exe /enum-drivers 2>&1
$blocks = New-Object System.Collections.ArrayList
$cur = $null

foreach ($line in $raw) {
    if ($line -match 'oem\d+\.inf') {
        if ($cur) { [void]$blocks.Add($cur) }
        $cur = @{ Oem = $matches[0]; Version = ''; Text = '' }
    }
    if ($cur) {
        $cur.Text += ($line + "`n")
        # 版本行:  "Driver Version: 03/14/2023 3.9.2023.3"
        #     或   "驱动程序版本:  03/14/2023 3.9.2023.3"
        if ($line -match '\d{1,2}[-/]\d{1,2}[-/]\d{4}[^\d]+(\d+\.\d+[\d.]*)') {
            $cur.Version = $matches[1]
        }
    }
}
if ($cur) { [void]$blocks.Add($cur) }

# 只保留沁恒 CH34x / USB-SERIAL 相关的包
$ch = @($blocks | Where-Object { $_.Text -match '(?i)ch34|wch|usb-serial|usbser|沁恒' })

if ($ch.Count -eq 0) {
    Write-Host '驱动存储里没有找到 CH34x 驱动包。' -ForegroundColor Yellow
    Write-Host '可能设备还没装过驱动, 或者驱动是非沁恒版本(先手动装一次 3.5 再跑本脚本)。'
}

Write-Host ('找到 ' + $ch.Count + ' 个 CH34x 驱动包:') -ForegroundColor White
for ($i = 0; $i -lt $ch.Count; $i++) {
    $b = $ch[$i]
    $mark = '  '
    if ($b.Version -like "$KeepVersion*") { $mark = 'OK' } else { $mark = 'XX' }
    Write-Host (('  [' + ($i + 1) + '] ' + $b.Oem).PadRight(22) + ' 版本: ' + $b.Version.PadRight(16) + '  ' + $mark)
}
Write-Host ''
Write-Host ('  OK = 保留(' + $KeepVersion + ')   XX = 将被删除') -ForegroundColor Gray

$keepList = @($ch | Where-Object { $_.Version -like "$KeepVersion*" })
$dropList = @($ch | Where-Object { -not ($_.Version -like "$KeepVersion*") })

if ($ch.Count -gt 0 -and $dropList.Count -eq 0 -and $keepList.Count -gt 0) {
    Write-Host '驱动存储里目前只有 3.5, 很干净。仍然继续写入防推送策略。' -ForegroundColor Green
}

# ---------------------------------------------------------------
# 2. 先锁门: 关闭 Windows 更新的驱动推送
# ---------------------------------------------------------------
Write-Section '写入策略: 禁止 Windows 更新推送驱动'

$policy = @(
    @{ Path = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate';
       Values = @{ 'ExcludeWUDriversInQualityUpdate' = 1 } },
    @{ Path = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\DriverSearching';
       Values = @{ 'SearchOrderConfig' = 0 } },
    @{ Path = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DeviceInstall\Settings';
       Values = @{ 'DisableSendGenericDriverNotFoundToWindowsUpdate' = 1;
                   'DisableSendRequestAdditionalSoftwareToWindowsUpdate' = 1 } }
)

foreach ($p in $policy) {
    if (-not (Test-Path $p.Path)) { New-Item -Path $p.Path -Force | Out-Null }
    foreach ($k in $p.Values.Keys) {
        New-ItemProperty -Path $p.Path -Name $k -Value $p.Values[$k] `
            -PropertyType DWord -Force | Out-Null
        Write-Host ('  已设置 ' + $k + ' = ' + $p.Values[$k]) -ForegroundColor Green
    }
}
Write-Host '  说明: SearchOrderConfig=0 等价于 设备安装设置 -> 否(不自动下载驱动)。' -ForegroundColor Gray

# ---------------------------------------------------------------
# 3. 再赶人: 删除 3.9(及所有非 3.5)驱动包
# ---------------------------------------------------------------
if ($dropList.Count -gt 0) {
    $bak = Join-Path $env:TEMP 'CH340_Driver_Backup'
    if (-not (Test-Path $bak)) { New-Item -Path $bak -ItemType Directory -Force | Out-Null }

    Write-Section ('备份并删除 ' + $dropList.Count + ' 个非 ' + $KeepVersion + ' 驱动包')
    Write-Host ('  备份目录: ' + $bak) -ForegroundColor Gray

    foreach ($b in $dropList) {
        Write-Host ('  [备份] ' + $b.Oem) -ForegroundColor DarkGray
        & pnputil.exe /export-driver $b.Oem $bak | Out-Null
    }
    foreach ($b in $dropList) {
        Write-Host ('  [删除] ' + $b.Oem + '  (版本 ' + $b.Version + ')') -ForegroundColor Yellow
        & pnputil.exe /delete-driver $b.Oem /uninstall /force
    }
} else {
    Write-Section '无需删除'
    Write-Host '  没有需要删除的 3.9 驱动包。'
}

# ---------------------------------------------------------------
# 4. 收尾检查
# ---------------------------------------------------------------
Write-Section '检查当前已连接设备的驱动版本'
$devs = @(Get-CimInstance Win32_PnPSignedDriver -Filter "DeviceName like '%CH34%' or DeviceName like '%USB-SERIAL%'" -ErrorAction SilentlyContinue)
if ($devs.Count -gt 0) {
    $devs | Select-Object DeviceName, DriverVersion, DriverProviderName | Format-Table -AutoSize
} else {
    Write-Host '  当前没有检测到已连接的 CH340 设备(可能已拔掉)。' -ForegroundColor Gray
}

Write-Section '完成'
if ($keepList.Count -eq 0) {
    Write-Host '注意: 驱动存储里没有 3.5 驱动包了, 请手动安装一次沁恒 CH341SER V3.5:' -ForegroundColor Yellow
    Write-Host '   1) 运行 CH341SER.EXE (V3.5) 安装'
    Write-Host '   2) 或者: pnputil /add-driver "D:\路径\CH341SER.INF" /install'
}
Write-Host ''
Write-Host '下一步, 请按顺序做:' -ForegroundColor Cyan
Write-Host '   1) 拔掉 D1 mini'
Write-Host '   2) 等 5 秒, 重新插入'
Write-Host '   3) 设备管理器 -> 端口(COM 和 LPT) 应显示 "USB-SERIAL CH340 (COMx)", 驱动版本为 3.5.x'
Write-Host ''
Read-Host '按回车关闭' | Out-Null
