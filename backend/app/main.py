import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
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


def ensure_schema():
    """Add columns/tables that create_all may miss on existing DBs."""
    with engine.begin() as conn:
        # departments.parent_id
        row = conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'departments' AND column_name = 'parent_id'
                """
            )
        ).first()
        if not row:
            conn.execute(
                text(
                    "ALTER TABLE departments ADD COLUMN parent_id INTEGER "
                    "REFERENCES departments(id)"
                )
            )

        # room_members.display_name (per-user room alias)
        row = conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'room_members' AND column_name = 'display_name'
                """
            )
        ).first()
        if not row:
            conn.execute(
                text("ALTER TABLE room_members ADD COLUMN display_name VARCHAR(200)")
            )

        # room_members.last_read_at (unread baseline; NULL = never accessed)
        row = conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'room_members' AND column_name = 'last_read_at'
                """
            )
        ).first()
        if not row:
            conn.execute(
                text("ALTER TABLE room_members ADD COLUMN last_read_at TIMESTAMP")
            )


        # room_members soft-leave columns
        for col, ddl in [
            ("status", "ALTER TABLE room_members ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active'"),
            ("left_at", "ALTER TABLE room_members ADD COLUMN left_at TIMESTAMP"),
            ("removed_by_id", "ALTER TABLE room_members ADD COLUMN removed_by_id INTEGER REFERENCES employees(id)"),
        ]:
            row = conn.execute(
                text(
                    f"""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'room_members' AND column_name = '{col}'
                    """
                )
            ).first()
            if not row:
                conn.execute(text(ddl))

        # messages system-notification columns
        for col, ddl in [
            ("is_system", "ALTER TABLE messages ADD COLUMN is_system BOOLEAN NOT NULL DEFAULT FALSE"),
            ("system_event", "ALTER TABLE messages ADD COLUMN system_event VARCHAR(20)"),
            ("system_actor_id", "ALTER TABLE messages ADD COLUMN system_actor_id INTEGER REFERENCES employees(id)"),
            ("system_target_id", "ALTER TABLE messages ADD COLUMN system_target_id INTEGER REFERENCES employees(id)"),
        ]:
            row = conn.execute(
                text(
                    f"""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'messages' AND column_name = '{col}'
                    """
                )
            ).first()
            if not row:
                conn.execute(text(ddl))

        # Do NOT COALESCE NULL -> now: NULL means never accessed and must count as unread.
        # One-time repair of join-stamp false reads (old create/invite set last_read_at=now).
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_flags (
                    flag VARCHAR(100) PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        flag = conn.execute(
            text("SELECT 1 FROM schema_flags WHERE flag = 'null_join_stamp_last_read'")
        ).first()
        if not flag:
            conn.execute(
                text(
                    """
                    UPDATE room_members
                    SET last_read_at = NULL
                    WHERE last_read_at IS NOT NULL
                      AND ABS(EXTRACT(EPOCH FROM (last_read_at - joined_at))) < 2
                    """
                )
            )
            conn.execute(
                text(
                    "INSERT INTO schema_flags(flag) VALUES ('null_join_stamp_last_read')"
                )
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    wait_for_db()
    Base.metadata.create_all(bind=engine)
    ensure_schema()
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
