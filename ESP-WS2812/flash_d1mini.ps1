<#
.SYNOPSIS
  WeMOS D1 mini 60 颗灯带固件一键烧录：检查工具链 -> 确认 CH340 端口 -> 释放被控制脚本占用的串口
  -> 编译固件 -> 串口复查 -> 复位进下载 / 写 flash / 回读校验 / 硬复位运行 -> 恢复后台灯效服务。

.DESCRIPTION
  这是干什么的：不打开 Arduino 图形界面，一条命令把 ESP-WS2812.ino
  编译并烧进 WeMOS D1 mini（4MB flash，板型 esp8266:esp8266:d1_mini）。
  固件收 60 颗 x 3B = 180B（逐颗独立控色），数据脚 D2/GPIO4，板载 LED D4/GPIO2，
  全局亮度硬限 50%；上电与 CMD_BRIGHTNESS 都先 clear()，保证没人推数据时灯带一定全灭。

  2026-11-09 硬件换回 D1 mini 后，这个脚本是**唯一在用的烧录入口**；
  ESP-01S-LightStrip-60/ 目录连同它的 flash_esp01s.ps1（板型 generic + eesz=1M64）已归档，
  只在把板子换回 ESP-01S 时才需要去翻。

  端口默认自动探测 CH340（留空 -Port）。换 USB 口、多个 CH340 同时在线都不用改脚本；
  想强制指定就 -Port COM3。串口被正在跑的灯效服务占用时，脚本会自动停它、烧完再还原。

  为什么不需要 Arduino IDE：
    arduino-cli 和 Arduino IDE 共用同一份已安装的 esp8266 core 与工具链
    (%LOCALAPPDATA%\Arduino15\packages\esp8266\hardware\esp8266\3.1.2)。
    IDE 只是图形外壳，脚本直接调命令行前端 —— IDE 开着、关着都不影响。

  为什么不需要额外装开发板 / 包（本机现状）：
    - esp8266 core 3.1.2 + xtensa-lx106-elf-gcc 编译器：已装
    - Adafruit_NeoPixel 库：已装（D:\Develope\Arduino\libraries）
    - CH340 驱动 3.5.2019.1：已装且正常
    - 烧录器 esptool 3.0 + pyserial：core 自带，upload.py 会自动加进 sys.path
    => 不依赖 WorkBuddy 的 Python，也不依赖系统 Python，不用 pip 装任何东西。
    前提失效时（换电脑 / 清掉 Arduino15 / 移动库目录）脚本会明确报错并给出修复命令。

  烧录四步是怎么落实的：
    ESP8266 core 的上传 recipe（platform.txt:182）自带
      --before default_reset --after hard_reset write_flash 0x0 <bin>
    即「复位进下载 -> 写 flash -> 硬复位运行」；esptool 3.0 的 write_flash 默认逐块读回校验。
    注意：arduino-cli 的 -t/--verify 在本 core 的 recipe 里没有被引用，是空转的，
    所以校验由 esptool 自己完成，脚本会解析上传输出确认校验痕迹。

  端口默认自动探测 CH340；想强制指定就 -Port COM3。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File "D:\Develope\esp8266\3.WeMOS D1 mini\ESP-WS2812\flash_d1mini.ps1" -DryRun

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File "D:\Develope\esp8266\3.WeMOS D1 mini\ESP-WS2812\flash_d1mini.ps1"
#>

param(
    [string]$Port = '',                           # 留空=自动探测 CH340；换 USB 口不用改，指定就 -Port COM3
    [switch]$NoBuild,                             # 跳过编译，直接烧上次编译的 bin
    [switch]$NoRestore,                           # 不自动恢复被停掉的后台灯效服务
    [switch]$DryRun                               # 只做检查，不改芯片、不停服务
)

$ErrorActionPreference = 'Stop'

# ---- 路径与配置：换电脑时只改这一段 ----
$ArduinoCli = Join-Path $env:LOCALAPPDATA 'Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe'
$ArduinoCfg = Join-Path $env:USERPROFILE '.arduinoIDE\arduino-cli.yaml'
$CoreRoot   = Join-Path $env:LOCALAPPDATA 'Arduino15\packages\esp8266\hardware\esp8266'
$SketchDir  = $PSScriptRoot
$SketchIno  = Join-Path $SketchDir 'ESP-WS2812.ino'
# WeMOS D1 mini = 4MB flash，直接用 core 内置的 d1_mini 板型，不指定 eesz。
# d1_mini 的 recipe 自带 --before default_reset --after hard_reset，
# 靠 USB 转串口的 DTR/RTS 自动进下载模式，不用手动按 FLASH 键。
$Fqbn       = "esp8266:esp8266:d1_mini"
$ReleaseWaitMs = 900

function Write-Step   { param([string]$Text) Write-Host ''; Write-Host "=== $Text ===" -ForegroundColor Cyan }
function Write-Ok     { param([string]$Text) Write-Host "  [OK] $Text" -ForegroundColor Green }
function Write-Notice { param([string]$Text) Write-Host "  [!!] $Text" -ForegroundColor Yellow }
function Write-Bad    { param([string]$Text) Write-Host ''; Write-Host "  [中止] $Text" -ForegroundColor Red }

function Test-PortFree {
    param([string]$Name)
    $sp = $null
    try {
        $sp = New-Object System.IO.Ports.SerialPort($Name, 115200)
        $sp.ReadTimeout = 200
        $sp.WriteTimeout = 200
        $sp.Open()
        $sp.Close()
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $sp) { try { $sp.Dispose() } catch {} }
    }
}

$stopped = @()      # 被本脚本停掉的 led_host.py 进程，finally 里按原参数还回去
$failed  = $false

try {
    # ---- 1/6 前置检查 ----------------------------------------------------
    Write-Step '1/6 检查工具链（全程不需要 Arduino 图形界面）'

    if (-not (Test-Path -LiteralPath $ArduinoCli -PathType Leaf)) {
        throw "找不到 arduino-cli：$ArduinoCli`n  装一下 Arduino IDE，或把脚本顶部的 `$ArduinoCli 改成实际路径。"
    }
    if (-not (Test-Path -LiteralPath $ArduinoCfg -PathType Leaf)) {
        throw "找不到 arduino-cli 配置：$ArduinoCfg"
    }
    if (-not (Test-Path -LiteralPath $SketchIno -PathType Leaf)) {
        throw "找不到固件源码：$SketchIno"
    }
    $cores = @(Get-ChildItem -LiteralPath $CoreRoot -Directory -ErrorAction SilentlyContinue)
    if ($cores.Count -eq 0) {
        throw "esp8266 core 没装（$CoreRoot 为空）。`n  修复：`"$ArduinoCli`" core install esp8266:esp8266"
    }
    Write-Ok "arduino-cli 可用；esp8266 core $($cores[-1].Name)"
    Write-Ok "固件源码 $SketchIno"
    Write-Ok "编译配置 $Fqbn"

    # ---- 2/6 探测 CH340 -------------------------------------------------
    Write-Step '2/6 探测 CH340 在线与否、在哪个 COM 口'

    $devs = @(Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match 'CH340|CH341' -and $_.Name -match '\(COM\d+\)'
    })
    if ($devs.Count -eq 0) {
        # WMI 有时枚举不到 PnP 端口名（驱动/权限差异），回退到 .NET 的串口列表。
        # 全空才是真的没插板子。
        $names = @([System.IO.Ports.SerialPort]::GetPortNames())
        if ($names.Count -eq 0) {
            throw '没检测到 CH340 串口。检查 USB 线是否插好、驱动是否正常，必要时跑 ch340-fix.bat。'
        }
        Write-Notice "WMI 未枚举到 CH340 设备名，回退到系统串口：$($names -join ', ')"
        $devs = @($names | ForEach-Object {
            [pscustomobject]@{ Name = "USB-SERIAL CH340 ($_)"; Status = 'OK' }
        })
    }
    # PnP 里可能残留多个历史 CH340 记录（COM3/4/5/6 都还在但已拔掉）。
    # 先筛出当前在线的 Status=OK，避免 $devs[0] 选中一个幽灵端口。
    $online = @($devs | Where-Object { $_.Status -eq 'OK' })
    if ($online.Count -gt 0) { $devs = $online }
    # 优先按 -Port 找对应设备。
    $dev = $devs | Where-Object { $_.Name -match "\($Port\)" } | Select-Object -First 1
    if (-not $dev) { $dev = $devs[0] }
    $foundPort  = 'COM' + [regex]::Match($dev.Name, '\(COM(\d+)\)').Groups[1].Value

    if ([string]::IsNullOrWhiteSpace($Port)) {
        $Port = $foundPort
    } elseif ($Port -ne $foundPort) {
        # 手写 -Port 时先确认这个口真的存在，别把「口不存在」误判成「被占用」
        $allPorts = @(Get-CimInstance Win32_PnPEntity |
            Where-Object { $_.Name -match '\(COM\d+\)' } |
            ForEach-Object { 'COM' + [regex]::Match($_.Name, '\(COM(\d+)\)').Groups[1].Value })
        if ($allPorts -notcontains $Port) {
            throw "指定的 $Port 在系统里不存在（当前 CH340 是 $foundPort）。留空 -Port 即可自动探测。"
        }
        Write-Notice "指定的 $Port 与探测到的 $foundPort 不一致，按指定值继续"
    }

    $drv = Get-CimInstance Win32_PnPSignedDriver |
           Where-Object { $_.DeviceName -match 'CH340|CH341' } | Select-Object -First 1
    if ($drv) {
        Write-Ok "CH340 在线 @ $foundPort，驱动 $($drv.DriverVersion)"
        if ($drv.DriverVersion -match '^3\.9') {
            Write-Notice '驱动 3.9 已知会让灯失效，建议先跑 ch340-fix.bat'
        }
    } else {
        Write-Ok "CH340 在线 @ $foundPort"
    }
    if ($dev.Status -ne 'OK') { Write-Notice "设备状态 $($dev.Status)，烧录可能失败" }
    Write-Ok "本次使用端口 $Port"

    # ---- 3/6 释放串口 ---------------------------------------------------
    Write-Step '3/6 确认串口可用（led_host_60.py 占用则停，其它程序占用则提醒）'

    if (Test-PortFree $Port) {
        Write-Ok "$Port 空闲，没有程序占用"
    } else {
        $led = @(Get-CimInstance Win32_Process | Where-Object {
            $_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'led_host_60\.py'
        })
        if ($led.Count -eq 0) {
            throw "$Port 被占用，但占用者不是 led_host_60.py。`n  请关闭 Arduino 串口监视器 / 其它串口工具后重试。脚本不会强杀未知进程。"
        }

        foreach ($p in $led) {
            $stopped += [pscustomobject]@{
                Pid = $p.ProcessId
                Exe = $p.ExecutablePath
                Cmd = $p.CommandLine
            }
        }

        if ($DryRun) {
            Write-Notice "占用者是 led_host_60.py（pid $($led.ProcessId -join ', ')）；DryRun 不真的停"
        } else {
            Write-Notice "占用者是 led_host_60.py，正在停止（pid $($led.ProcessId -join ', ')）"
            foreach ($p in $led) {
                Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Milliseconds $ReleaseWaitMs
            if (-not (Test-PortFree $Port)) {
                throw "已停 led_host_60.py，但 $Port 仍打不开 —— 还有别的程序占着，请手动排查后再烧。"
            }
            Write-Ok "$Port 已释放"
        }
    }

    # ---- 4/6 编译 -------------------------------------------------------
    Write-Step '4/6 编译固件'

    if ($NoBuild) {
        Write-Notice '已指定 -NoBuild，跳过编译（直接烧上次编译的 bin）'
    } elseif ($DryRun) {
        Write-Notice 'DryRun 不编译'
    } else {
        $compileOut = @()
        & $ArduinoCli compile --config-file $ArduinoCfg --fqbn $Fqbn $SketchDir 2>&1 |
            Tee-Object -Variable compileOut | ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -ne 0) { throw '编译失败，没有烧任何东西' }
        Write-Ok '编译通过（内存报告见上方）'
    }

    # ---- 5/6 烧录 -------------------------------------------------------
    Write-Step '5/6 复位进下载 -> 写 flash -> 回读校验 -> 硬复位运行'

    if ($DryRun) {
        Write-Notice "DryRun 不烧录。实际命令：arduino-cli upload -p $Port -b $Fqbn"
    } else {
        # 编译这段时间里串口可能被别的程序重新占上，烧之前再确认一次
        if (-not (Test-PortFree $Port)) {
            throw "编译完成后 $Port 又被占用了，为安全起见不烧录。"
        }
        Write-Ok "烧前复查 $Port 仍可用"

        $uploadOut = @()
        & $ArduinoCli upload --config-file $ArduinoCfg -p $Port -b $Fqbn $SketchDir 2>&1 |
            Tee-Object -Variable uploadOut | ForEach-Object { Write-Host "    $_" }
        if ($LASTEXITCODE -ne 0) {
            throw '烧录失败。后台服务会在最后自动恢复。'
        }

        $txt = $uploadOut | Out-String
        if ($txt -match 'Hash of data verified|Verifying just-written|Verifying|verify_flash') {
            Write-Ok '写 flash 后的回读校验：通过'
        } else {
            Write-Notice '上传输出里没看到显式校验行（esptool 输出格式可能不同），但上传命令返回成功'
        }
        if ($txt -match 'Hard resetting|hard_reset|Leaving') {
            Write-Ok '硬复位：已执行，新固件开始运行'
        } else {
            Write-Notice '没看到硬复位提示；core 的 recipe 默认带 --after hard_reset'
        }
        Write-Ok '烧录完成'
    }
}
catch {
    Write-Bad $_.Exception.Message
    $failed = $true
}
finally {
    # ---- 6/6 把后台灯效服务还回去 ---------------------------------------
    # 用 try/finally 是刻意的：哪怕编译 / 烧录失败，也不能让灯一直黑着。
    if ($stopped.Count -gt 0 -and -not $DryRun) {
        Write-Step '6/6 恢复后台灯效服务'
        if ($NoRestore) {
            Write-Notice '已指定 -NoRestore，不自动恢复。手动起：python led_host_60.py --autostart start'
        } else {
            # 顺序：计划任务 > 启动文件夹的 VBS 启动器 > 直接 Start-Process。
            # 只有前两种能真正脱离终端会话；Start-Process 起的 pythonw 会随终端关闭被回收。
            $TaskName = 'ESP-WS2812 60颗音乐灯带'
            $VbsPath  = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\ESP-WS2812 60颗音乐灯带.vbs'
            $restored = $false
            try {
                if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
                    Start-ScheduledTask -TaskName $TaskName
                    Start-Sleep -Seconds 2
                    $restored = $true
                    Write-Ok "已通过计划任务「$TaskName」恢复灯效服务"
                }
            } catch {
                Write-Notice "计划任务拉起失败：$($_.Exception.Message)"
            }
            if (-not $restored -and (Test-Path -LiteralPath $VbsPath)) {
                try {
                    & wscript.exe $VbsPath
                    Start-Sleep -Seconds 3
                    $restored = $true
                    Write-Ok "已通过启动器 VBS 恢复灯效服务（未注册计划任务，崩溃不会自动重启）"
                } catch {
                    Write-Notice "VBS 启动器执行失败：$($_.Exception.Message)"
                }
            }
            if (-not $restored) {
                foreach ($s in $stopped) {
                    # 去掉命令行开头那个带引号的 exe 路径，剩下的参数原样传回，避免参数被改掉
                    $argLine = ($s.Cmd -replace '^\s*"[^"]+"\s*', '').Trim()
                    try {
                        Start-Process -FilePath $s.Exe -ArgumentList $argLine -WindowStyle Hidden | Out-Null
                        Write-Notice "已用 Start-Process 重启（原 pid $($s.Pid)）—— 可能随终端关闭被回收，建议改用 --autostart start"
                    } catch {
                        Write-Notice "自动恢复失败：$($_.Exception.Message)。手动跑：python led_host_60.py --autostart start"
                    }
                }
            }
        }
    }
}

if ($failed) { exit 1 }
Write-Host ''
Write-Host '完成。' -ForegroundColor Green
