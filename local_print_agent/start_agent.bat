@echo off
set "AGENT_DIR=%LOCALAPPDATA%\FrigoDatta\PrintAgent"
if not exist "%AGENT_DIR%" mkdir "%AGENT_DIR%"
start "" /b python "%~dp0agent.py" run > "%AGENT_DIR%\agent.log" 2>&1
