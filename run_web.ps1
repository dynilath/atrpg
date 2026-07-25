# ATRPG Web 启动脚本（PowerShell）
# 开发模式：分离启动 FastAPI 后端 + Vite 前端
#   - 后端：web_api/.venv，端口 9090
#   - 前端：pnpm dev，端口 5173（Vite 内置 proxy → 后端）
# 用法：pwsh -File run_web.ps1

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

Set-Location $PSScriptRoot

# ── 后端 venv ──
$backendDir = Join-Path $PSScriptRoot 'web_api'
$python = Join-Path $backendDir '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host '[ATRPG Web] 未找到后端 venv，自动创建中...' -ForegroundColor Yellow

    $sysPython = $null
    $candidates = @(
        'C:\Users\admin\.workbuddy\binaries\python\versions\3.13.12\python.exe'
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $sysPython = $c; break }
    }
    if (-not $sysPython) {
        $sysPython = (Get-Command python3 -ErrorAction SilentlyContinue).Source
    }
    if (-not $sysPython) {
        $sysPython = (Get-Command python -ErrorAction SilentlyContinue).Source
    }
    if (-not $sysPython) {
        Write-Host '[错误] 找不到系统 Python' -ForegroundColor Red
        Read-Host '按回车关闭'
        exit 1
    }

    Write-Host "  使用: $sysPython"
    & $sysPython -m venv "$backendDir\.venv"
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[错误] venv 创建失败' -ForegroundColor Red
        Read-Host '按回车关闭'
        exit 1
    }

    Write-Host '  安装后端依赖...'
    & $python -m pip install fastapi "uvicorn[standard]" openai pyyaml httpx tomli-w --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[错误] 依赖安装失败' -ForegroundColor Red
        Read-Host '按回车关闭'
        exit 1
    }
    Write-Host '[ATRPG Web] 后端 venv 就绪' -ForegroundColor Green
}

# ── 前端检查 ──
$frontendDir = Join-Path $PSScriptRoot 'web_frontend'
if (-not (Test-Path (Join-Path $frontendDir 'node_modules'))) {
    Write-Host '[ATRPG Web] 安装前端依赖...' -ForegroundColor Yellow
    Push-Location $frontendDir
    pnpm install
    Pop-Location
}

# ── 启动后端 ──
Write-Host ''
Write-Host '[ATRPG Web] 启动后端 (127.0.0.1:9090)...' -ForegroundColor Cyan
$env:PYTHONPATH = $PSScriptRoot
$backendJob = Start-Job -ScriptBlock {
    param($py, $root)
    $env:PYTHONPATH = $root
    Set-Location $root
    & $py -c "import sys; sys.path.insert(0, r'$root\web_api'); sys.path.insert(0, r'$root'); from web_api.main import main; main()"
} -ArgumentList $python, $PSScriptRoot

# ── 等后端就绪 ──
Write-Host '  等待后端就绪...'
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $null = Invoke-WebRequest -Uri 'http://127.0.0.1:9090/api/sessions' -UseBasicParsing -TimeoutSec 1
        $ready = $true
        break
    } catch {}
    if ($backendJob.State -ne 'Running') {
        Write-Host '[错误] 后端启动失败' -ForegroundColor Red
        Receive-Job $backendJob
        Read-Host '按回车关闭'
        exit 1
    }
}
if ($ready) {
    Write-Host '  后端就绪: http://127.0.0.1:9090' -ForegroundColor Green
} else {
    Write-Host '[警告] 后端启动超时，继续启动前端...' -ForegroundColor Yellow
}

# ── 启动前端 ──
Write-Host '[ATRPG Web] 启动前端 (pnpm dev)...' -ForegroundColor Cyan
Write-Host ''
Write-Host '  ┌─────────────────────────────────────┐'
Write-Host '  │  前端:  http://localhost:5173        │'
Write-Host '  │  后端:  http://127.0.0.1:9090/api/   │'
Write-Host '  │  按 Ctrl+C 停止所有服务              │'
Write-Host '  └─────────────────────────────────────┘'
Write-Host ''

Push-Location $frontendDir
try {
    pnpm dev
} finally {
    Pop-Location
    Write-Host ''
    Write-Host '[ATRPG Web] 停止后端...' -ForegroundColor Yellow
    Stop-Job $backendJob -ErrorAction SilentlyContinue
    Remove-Job $backendJob -ErrorAction SilentlyContinue
    Write-Host '[ATRPG Web] 已停止' -ForegroundColor Cyan
}
