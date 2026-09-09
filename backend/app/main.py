import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.database import Base, engine, SessionLocal
from app.seed import seed_database
from app.routers import auth_router, org, rooms, notes, ws


def wait_for_db(retries: int = 30, delay: float = 1.0):
    for i in range(retries):
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return
        except OperationalError:
            time.sleep(delay)
    raise RuntimeError("Database not available")


@asynccontextmanager
async def lifespan(_: FastAPI):
    wait_for_db()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()
    yield


app = FastAPI(title="기업 메신저 MVP", version="0.1.0", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(org.router)
app.include_router(rooms.router)
app.include_router(notes.router)
app.include_router(ws.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "기업 메신저 API"}
