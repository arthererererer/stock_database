@echo off
REM 雙擊或從 CMD 呼叫：開啟互動爬蟲（與 18:00 排程相同流程）
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Normal -File "%~dp0run_daily_tip_interactive.ps1"
