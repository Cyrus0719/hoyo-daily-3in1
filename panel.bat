@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "config_center\api.py"
) else (
  echo [!] 没找到 .venv，请先运行: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  pause
)
