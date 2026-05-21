@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Normal -File "%~dp0scripts\run_daily_tip_interactive.ps1"
