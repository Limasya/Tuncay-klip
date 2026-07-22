@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Tuncay Klip - Gelistirme
echo.
echo  ============================================
echo    Tuncay Klip - Gelistirme Ortami Baslatiliyor
echo  ============================================
echo.
python dev.py
pause
