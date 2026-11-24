@echo off
chcp 65001 >nul
cd /d "%~dp0..\ui"
echo Career Manager - UI preview (design mockup with TEST data)
echo Open in browser: http://127.0.0.1:8765/index.html
start "" http://127.0.0.1:8765/index.html
python -m http.server 8765 --bind 127.0.0.1
