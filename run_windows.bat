@echo off
cd /d C:\coding\weekly-work-plan-collector
wsl -e bash -lc "cd /mnt/c/coding/weekly-work-plan-collector && uv run --with fastapi --with uvicorn --with pydantic uvicorn app:app --host 0.0.0.0 --port 8792"
pause
