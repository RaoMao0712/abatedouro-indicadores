@echo off
for /f "tokens=2" %%P in ('wmic process where "CommandLine like '%%local_print_agent%%agent.py run%%'" get ProcessId 2^>nul ^| findstr /r "[0-9]"') do taskkill /PID %%P /T
