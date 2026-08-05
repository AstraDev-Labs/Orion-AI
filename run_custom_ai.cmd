@echo off
echo Starting Custom AI (Llama.cpp Server)
echo =======================================
echo Base Model: base.gguf
echo Adapter:    orion_lora.gguf
echo Hardware:   RTX 2050 (4GB) 
echo =======================================

cd /d "%~dp0"

:: -m is the base model
:: --lora is the adapter
:: -ngl is the number of GPU layers to offload. 
:: We use 20 to ensure it fits in 4GB VRAM along with the context.
:: -c 2048 is the context window.
:: --port 8080 is the default Orion expected port for llamacpp engine.

llama.cpp\bin\llama-server.exe -m base.gguf --lora orion_lora.gguf -ngl 20 -c 4096 --port 8080

pause
