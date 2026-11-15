@echo off
chcp 65001 >nul
title Gerar versao do AcroBot
cd /d "%~dp0"
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY (
    echo ERRO: Python nao encontrado.
    pause
    exit /b 1
)
%PY% gerar_versao.py
echo.
pause
