@echo off
rem Start the dashboard (Next.js dev server) from ANY terminal and ANY folder:
rem     frontend\dev.cmd
rem It finds the portable Node.js in %LOCALAPPDATA%\nodejs even if this terminal was
rem opened before Node.js was added to PATH.
setlocal
if exist "%LOCALAPPDATA%\nodejs\node.exe" set "PATH=%LOCALAPPDATA%\nodejs;%PATH%"
where npm >nul 2>nul || (echo Node.js not found. Install it or check %%LOCALAPPDATA%%\nodejs & exit /b 1)
cd /d "%~dp0"
if not exist node_modules (echo First run: installing packages... & call npm install || exit /b 1)
call npm run dev -- %*
