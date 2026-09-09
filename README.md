# Enterprise Messenger MVP

See .env.example. Seed users E001-E004 password password123.
UI port 3000. API port 8000.

## Stack
- React Vite TypeScript
- FastAPI
- WebSockets
- PostgreSQL
- compose.yml for services

## Run
1. copy env example
2. compose up --build
3. localhost:3000 UI, localhost:8000/docs API

## Seed
E001-E004 demo password in seed module. AI-BOT no login.

## Local
See backend and frontend folders for local run.

## Blocker on Windows hosts
Docker Desktop is installed but the engine needs WSL2. If wsl -l fails, run admin: wsl --install then reboot, then compose up --build.
