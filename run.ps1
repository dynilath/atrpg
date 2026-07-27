# ATRPG 统一启动脚本（PowerShell）
#
# 默认生产模式：先构建前端，后端直接服务静态文件。
# -ViteDev：开发模式，Vite 热更新代理到后端。
#
# QQ Bot 按 config.toml 中的凭据按需注册。
#
# 用法：
#   pwsh -File run.ps1                # 生产模式
#   pwsh -File run.ps1 -ViteDev        # 开发模式（Vite 热更新）
#   pwsh -File run.ps1 -Setup          # 首次配置向导
#   pwsh -File run.ps1 -NoFrontend     # 纯后端（不构建也不启动 Vite）

param(
    [switch]$ViteDev,     # 开发模式：Vite 热更新
    [switch]$Setup,       # 交互式配置向导
    [switch]$NoFrontend,  # 跳过前端
    [string]$GameDir      # 游戏工作目录（优先级高于 config.toml）
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# ---- 后端 venv ----
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host '[ATRPG] 未找到项目 .venv，自动创建中...' -ForegroundColor Yellow

    $sysPython = $null
    $candidates = @(
        'C:\Users\admin\.workbuddy\binaries\python\versions\3.13.12\python.exe'
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $sysPython = $c; break }
    }
    if (-not $sysPython) { $sysPython = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
    if (-not $sysPython) { $sysPython = (Get-Command python -ErrorAction SilentlyContinue).Source }
    if (-not $sysPython) {
        Write-Host '[错误] 找不到系统 Python' -ForegroundColor Red; Read-Host '按回车关闭'; exit 1
    }

    Write-Host "  使用: $sysPython"
    & $sysPython -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[错误] venv 创建失败' -ForegroundColor Red; Read-Host '按回车关闭'; exit 1
    }

    Write-Host '  安装依赖...'
    & $python -m pip install qqbot-agent-sdk fastapi uvicorn openai pyyaml httpx tomli-w --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[错误] 依赖安装失败' -ForegroundColor Red; Read-Host '按回车关闭'; exit 1
    }
    Write-Host '[ATRPG] venv 创建完成' -ForegroundColor Green
}

# ---- 前端 ----
$frontendDir = Join-Path $PSScriptRoot 'web_frontend'

if ($NoFrontend) {
    $isDist = $false
} elseif ($ViteDev) {
    # 开发模式：确保依赖，不构建
    if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
        Write-Host '[ATRPG] 安装前端依赖...' -ForegroundColor Yellow
        Push-Location $frontendDir; pnpm install; Pop-Location
    }
    $isDist = $false
} else {
    # 默认生产模式：构建前端
    if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
        Write-Host '[ATRPG] 安装前端依赖...' -ForegroundColor Yellow
        Push-Location $frontendDir; pnpm install; Pop-Location
    }
    Write-Host '[ATRPG] 构建前端 (pnpm build)...' -ForegroundColor Cyan
    Push-Location $frontendDir
    pnpm build
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[错误] 前端构建失败' -ForegroundColor Red
        Pop-Location; Read-Host '按回车关闭'; exit 1
    }
    Pop-Location
    Write-Host '  构建完成: web_frontend/dist/' -ForegroundColor Green
    $isDist = $true
}

# ---- 读取配置（端口）----
$configToml = Join-Path $PSScriptRoot 'config.toml'
$backendPort = 8080
if (Test-Path $configToml) {
    $match = Select-String -Path $configToml -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -First 1
    if ($match) { $backendPort = [int]$match.Matches.Groups[1].Value }
}
$backendHost = '127.0.0.1'

# ---- 后端日志 ----
$logFile = Join-Path $PSScriptRoot 'backend.log'
try {
    if (Test-Path $logFile) {
        Add-Content -Path $logFile -Value ("`n" + "=" * 60)
        Add-Content -Path $logFile -Value "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') --- 新会话启动 ($(if ($isDist) {'dist'} else {'dev'}))"
        Add-Content -Path $logFile -Value ("=" * 60 + "`n")
    }
} catch {
    $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
    $logFile = Join-Path $PSScriptRoot "backend-$ts.log"
    Write-Host "  日志文件被占用，改用: $logFile" -ForegroundColor DarkGray
}

# ---- 启动后端 ----
$modeLabel = if ($isDist) { '生产模式' } else { '开发模式' }
Write-Host "[ATRPG] 启动后端 ($modeLabel, ${backendHost}:$backendPort)..." -ForegroundColor Cyan
$env:PYTHONPATH = $PSScriptRoot

$passArgs = @()
if ($Setup) { $passArgs += '--setup' }
if ($isDist) { $passArgs += '--dist' }
if ($GameDir) { $passArgs += '--game-dir'; $passArgs += $GameDir }

$backendJob = Start-Job -ScriptBlock {
    param($py, $root, $log, $pyArgs)
    $env:PYTHONPATH = $root
    Set-Location $root
    & $py run.py @pyArgs *>&1 | Out-File -FilePath $log -Append -Encoding UTF8
} -ArgumentList $python, $PSScriptRoot, $logFile, $passArgs

# ---- 等后端就绪 ----
Write-Host '  等待后端就绪...'
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $conn = New-Object Net.Sockets.TcpClient
        $conn.Connect($backendHost, $backendPort)
        $conn.Close()
        $ready = $true
        break
    } catch {}
    if ($backendJob.State -ne 'Running') {
        Write-Host '[错误] 后端启动失败，最后 20 行日志:' -ForegroundColor Red
        Get-Content $logFile -Tail 20
        Read-Host '按回车关闭'
        exit 1
    }
}
if (-not $ready) {
    Write-Host '[警告] 后端启动超时' -ForegroundColor Yellow
}

Write-Host "[ATRPG] 后端就绪: http://${backendHost}:$backendPort" -ForegroundColor Green

# ---- 执行 ----
try {
    # dist / nofrontend 模式：等待用户 Ctrl+C
    if ($isDist -or $NoFrontend) {
        if ($isDist) {
            Write-Host ''
            Write-Host '  +-----------------------------------------+'
            Write-Host '  |  生产模式                                |'
            Write-Host "  |  http://${backendHost}:$backendPort                   |"
            Write-Host '  |  按 Ctrl+C 停止                          |'
            Write-Host '  +-----------------------------------------+'
            Write-Host ''
        } else {
            Write-Host '[ATRPG] 无前端模式' -ForegroundColor DarkGray
        }
        while ($true) {
            Start-Sleep -Seconds 1
            if ($backendJob.State -ne 'Running') { break }
        }
    } else {
        # ViteDev 模式
        Write-Host '[ATRPG] 启动前端 Vite (pnpm dev)...' -ForegroundColor Cyan
        Write-Host ''
        Write-Host '  +-----------------------------------------+'
        Write-Host '  |  开发模式 (Vite)                         |'
        Write-Host '  |  前端:  http://localhost:5173            |'
        Write-Host "  |  后端:  http://${backendHost}:$backendPort/api/       |"
        Write-Host '  |  按 Ctrl+C 停止所有服务                  |'
        Write-Host '  +-----------------------------------------+'
        Write-Host ''
        $env:VITE_BACKEND_PORT = "$backendPort"
        Push-Location $frontendDir
        try { pnpm dev } finally { Pop-Location }
    }
} finally {
    # ---- 清理 ----
    Write-Host ''
    Write-Host '[ATRPG] 停止后端...' -ForegroundColor Yellow
    Stop-Job $backendJob -ErrorAction SilentlyContinue
    Receive-Job $backendJob -ErrorAction SilentlyContinue | Add-Content -Path $logFile -Encoding UTF8
    Remove-Job $backendJob -ErrorAction SilentlyContinue
    Write-Host '[ATRPG] 已停止' -ForegroundColor Cyan
}
