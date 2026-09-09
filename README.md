# Enterprise Messenger MVP

See .env.example. Seed users F00001-F00010 password 1q2w3e1!.
UI port 3000 (Vite local default 5173; use --port 3000). API port 8000.

## Stack
- React Vite TypeScript
- FastAPI
- WebSockets
- PostgreSQL
- compose.yml for services (optional; Windows hosts without WSL2 should use native local run)

## Seed
| 사번 | 이름 | 부서 | 비밀번호 |
|------|------|------|----------|
| F00001 | 김민수 | 경영지원팀 | 1q2w3e1! |
| F00002 | 이서연 | 개발팀 | 1q2w3e1! |
| F00003 | 박준호 | 개발팀 | 1q2w3e1! |
| F00004 | 최유진 | 영업팀 | 1q2w3e1! |
| F00005 | 정하늘 | 경영지원팀 | 1q2w3e1! |
| F00006 | 오세훈 | 개발팀 | 1q2w3e1! |
| F00007 | 한지민 | 개발팀 | 1q2w3e1! |
| F00008 | 윤서아 | 영업팀 | 1q2w3e1! |
| F00009 | 강도윤 | 경영지원팀 | 1q2w3e1! |
| F00010 | 임채원 | 영업팀 | 1q2w3e1! |
| AI-BOT | AI 도우미 | (bot, no login) | — |

## Local (Windows, no Docker)
1. Copy .env.example → .env and ackend/.env with DATABASE_URL=postgresql://messenger:messenger@127.0.0.1:5432/messenger
2. Ensure native PostgreSQL is running; create role/db messenger/messenger
3. Backend: cd backend → python -m venv .venv → .venv\Scripts\activate → pip install -r requirements.txt → uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
4. Frontend: cd frontend → 
pm install → 
pm run dev -- --port 3000 --host
5. Open http://localhost:3000 and http://localhost:8000/docs

See LOCAL_DEV.md for details.
