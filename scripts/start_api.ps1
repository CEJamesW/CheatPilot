$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "C:\Users\Administrator\Desktop\CheatPilot"
python -m uvicorn cheatpilot.api:app --host 127.0.0.1 --port 8765
