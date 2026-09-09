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

## PowerShell + Korean (UTF-8) API calls

Windows PowerShell 5.x often mangles Korean in JSON POST bodies when you pass a .NET string to `Invoke-RestMethod -Body` (default encoding is not UTF-8). Use the helper instead of raw `Invoke-RestMethod`.

### Helper: `scripts/Invoke-MessengerApi.ps1`

Dot-source once per session:

```powershell
cd C:\Users\F00176_daas\projects\071050
. .\scripts\Invoke-MessengerApi.ps1
```

What it does:
- `chcp 65001` + UTF-8 console/`$OutputEncoding`
- POST JSON with `Content-Type: application/json; charset=utf-8`
- Request/response via `HttpWebRequest` + UTF-8 `StreamReader` (PS 5.x `Invoke-RestMethod` mangles Korean on both POST body and GET decode)

### Login

```powershell
$tok = Connect-Messenger -EmployeeId 'F00001' -Password '1q2w3e1!'
# optional: -TokenPath '.\f00001_token.txt'
```

### Send a Korean chat message and verify round-trip

```powershell
$roomId = 15   # use a room you belong to
$expected = '한글 인코딩 검증 메시지'
$msg = Send-MessengerMessage -RoomId $roomId -Content $expected -Token $tok -ClientMessageId ([guid]::NewGuid().ToString('N'))
$all = Get-MessengerMessages -RoomId $roomId -Token $tok
$got = ($all | Where-Object { $_.id -eq $msg.id }).content
if ($got -ceq $expected) { 'VERIFY_OK exact match' } else { "VERIFY_FAIL got=[$got]" }
```

### Notes (쪽지)

```powershell
# recipient_ids = employees.id (DB PK), not 사번
Send-MessengerNote -RecipientIds @(2) -Subject '제목' -Content '쪽지 본문 한글' -Token $tok
```

### Low-level API

```powershell
Invoke-MessengerApi -Method Get -Path '/api/auth/me' -Token $tok
Invoke-MessengerApi -Method Post -Path '/api/rooms/15/messages' -Token $tok -Body @{ content = '안녕하세요' }
```

### QA scripts

Repo QA/debate `.ps1` scripts should dot-source this helper (see `.qa-f00003-step1.ps1`) instead of hand-rolling `ConvertTo-Json` + `Invoke-RestMethod`.