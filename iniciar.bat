@echo off
REM Arranque rapido en Windows (despues de la instalacion del README)
call .venv\Scripts\activate
docker compose up -d
start "" http://localhost:8000
uvicorn app.main:app --port 8000
