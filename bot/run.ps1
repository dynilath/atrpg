# ATRPG Bot 启动脚本（PowerShell）
# 用项目内的 .venv，无需手动激活，项目自包含
# 用法：在 bot 目录下  pwsh -File run.ps1   或   powershell -File run.ps1
#      首次配置：pwsh -File run.ps1 -Setup

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'

# 切到脚本所在目录（项目 bot 目录）
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host '[ATRPG Bot] 未找到 .venv，自动创建中...' -ForegroundColor Yellow

    # 找系统 Python：优先用已知路径，其次 python3 / python
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
        Write-Host "[错误] 找不到系统 Python，无法自动创建 venv" -ForegroundColor Red
        Read-Host '按回车关闭'
        exit 1
    }

    Write-Host "  使用: $sysPython"
    & $sysPython -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] venv 创建失败" -ForegroundColor Red
        Read-Host '按回车关闭'
        exit 1
    }

    Write-Host '  安装依赖...'
    & $python -m pip install -e . --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 依赖安装失败" -ForegroundColor Red
        Read-Host '按回车关闭'
        exit 1
    }
    Write-Host '[ATRPG Bot] venv 创建完成' -ForegroundColor Green
}

Write-Host '[ATRPG Bot] 使用项目 venv 启动...' -ForegroundColor Cyan
Write-Host ''

$passArgs = @()
if ($Setup) { $passArgs += '--setup' }

try {
    & $python run.py @passArgs
} catch {
    Write-Host ''
    Write-Host "[启动失败] $($_.Exception.Message)" -ForegroundColor Red
    Read-Host '按回车关闭'
    exit 1
}