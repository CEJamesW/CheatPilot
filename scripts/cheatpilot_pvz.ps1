$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "C:\Users\Administrator\Desktop\CheatPilot"

$message = $args -join " "
if ([string]::IsNullOrWhiteSpace($message)) {
    $message = "我在玩植物大战僵尸，现在的阳光是100。帮我把阳光修改成99999，并打印出阳光基址"
}

python -m cheatpilot $message
