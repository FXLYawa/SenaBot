@echo off
setlocal
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 goto missing_node
if not exist ".venv\Scripts\python.exe" goto missing_python
cd frontend
if not exist "node_modules\.bin\electron.cmd" (
  call npm.cmd ci
  if errorlevel 1 goto failed
)
call npm.cmd run electron:start
if errorlevel 1 goto failed
exit /b 0
:missing_node
echo Please install Node.js and reopen this launcher.
goto failed
:missing_python
echo Missing .venv. Create it and install requirements.txt first.
:failed
pause
exit /b 1
