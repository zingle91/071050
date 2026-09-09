# Local development (Windows, no Docker)

Native stack: PostgreSQL 16 + FastAPI (uvicorn) + Vite.

## Prerequisites
- Python 3.12+
- Node.js 20+
- PostgreSQL 16 listening on 127.0.0.1:5432

## Database
Connection string (also in .env / ackend/.env):

`
DATABASE_URL=postgresql://messenger:messenger@127.0.0.1:5432/messenger
`

Postgres superuser (installer): postgres / MessengerLocal1!

Create role/db if missing (as postgres):

`
CREATE ROLE messenger LOGIN PASSWORD 'messenger';
CREATE DATABASE messenger OWNER messenger;
`

## Backend
`
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
`

API: http://127.0.0.1:8000/api/health and http://127.0.0.1:8000/docs

Tables + seed run automatically on startup. Seed humans: F00001–F00010 / 1q2w3e1!. AI-BOT is not a login account.

## Frontend
`
cd frontend
npm install
npm run dev -- --port 3000 --host
`

UI: http://127.0.0.1:3000 (Vite proxies /api and /ws to :8000)

## Notes
Do not use Docker Desktop / WSL2 on hosts where nested virt is unsupported.
