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
    Write-Host "[错误] 找不到项目 venv: $python" -ForegroundColor Red
    Write-Host '请先创建并装依赖：' -ForegroundColor Yellow
    Write-Host '  "C:\Users\admin\.workbuddy\binaries\python\versions\3.13.12\python.exe" -m venv .venv'
    Write-Host '  .venv\Scripts\python.exe -m pip install nonebot2 nonebot-adapter-qq pyyaml openai httpx'
    Read-Host '按回车关闭'
    exit 1
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