$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$log = Join-Path $projectRoot "start_app.log"

Start-Transcript -Path $log -Append | Out-Null

if (-not (Test-Path $python)) {
    Write-Error "未找到虚拟环境 Python：$python。请先创建 .venv 并安装 requirements.txt。"
}

Set-Location $projectRoot
& $python -m flask --app app run --host 127.0.0.1 --port 5000 --no-reload
