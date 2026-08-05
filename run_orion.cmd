@echo off
title ORION Unified Launcher
color 0B

echo ======================================================================
echo    ____  _____  _____  ____  _   _ 
echo   / __ \^|  __ \^|_   _^|/ __ \^| \ ^| ^|
echo  ^| ^|  ^| ^| ^|__) ^| ^| ^| ^| ^|  ^| ^|  \^| ^|
echo  ^| ^|  ^| ^|  _  /  ^| ^| ^| ^|  ^| ^| . ` ^|
echo  ^| ^|__^| ^| ^| \ \ _^| ^|_^| ^|__^| ^| ^|\  ^|
echo   \____/^|_^|  \_\_____^|\____/^|_^| \_^|
echo ======================================================================
echo           [ ORION 3D CONSOLE HUD - UNIFIED LAUNCHER ]
echo ======================================================================
echo.
echo  [SYSTEM] Waking up ORION core systems...
echo.

:: 1. Build React Frontend
echo  [FRONTEND] Building 3D Voice Console HUD...
cd frontend
if not exist "node_modules" (
    echo  [FRONTEND] Installing dependencies...
    call npm.cmd install
)
call npm.cmd run build
cd ..

:: 2. Launch Python API Backend (which will also serve the frontend)
echo.
echo  [ENGINE] Starting Ollama Inference Engine...
start /B ollama serve >nul 2>&1

echo  [BACKEND] Starting ORION Unified Server...
echo  --------------------------------------------------
echo   Voice Console ^& API: http://127.0.0.1:8000
echo  --------------------------------------------------
echo.
set PYTHONPATH=src
set OPENORION_CONFIG=configs\orion\config.toml
call uv sync --extra server
.venv\Scripts\python.exe -m orion.cli serve
if errorlevel 1 (
    echo  [ERROR] Failed to start Server.
    pause
    exit /b 1
)
