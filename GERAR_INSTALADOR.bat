@echo off
rem Prumo PDF - gera o instalador. De dois cliques neste arquivo.
title Prumo PDF - gerando o instalador
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build\build.ps1"
echo.
pause
