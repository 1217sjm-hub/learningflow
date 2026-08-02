from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATA_DIR, settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.database_url
    connect_args = {}
    if url.startswith("sqlite"):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    eng = create_engine(url, connect_args=connect_args, future=True)

    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _sqlite_pragma(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return eng


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """테이블 생성. (마이그레이션 도구 도입 전 단계)"""
    from sqlalchemy import text

    from . import models  # noqa: F401
    from .config import settings

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)

    # 기존 SQLite 테이블에 컬럼 추가 (create_all 은 신규 컬럼을 안 넣음)
    if settings.database_url.startswith("sqlite"):
        with engine.begin() as conn:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
            if cols and "is_admin" not in cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0 NOT NULL"))
            course_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(courses)")).fetchall()}
            if course_cols and "folder_id" not in course_cols:
                conn.execute(text("ALTER TABLE courses ADD COLUMN folder_id VARCHAR(64)"))
            folder_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(course_folders)")).fetchall()}
            if folder_cols and "parent_id" not in folder_cols:
                conn.execute(text("ALTER TABLE course_folders ADD COLUMN parent_id VARCHAR(64)"))

            run_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(runs)")).fetchall()}
            if run_cols and "board_version" not in run_cols:
                conn.execute(text("ALTER TABLE runs ADD COLUMN board_version INTEGER"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_runs_board_version ON runs (board_version)"))

            week_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(weeks)")).fetchall()}
            if week_cols:
                needs_rebuild = False
                if "session_no" not in week_cols or "week_title" not in week_cols:
                    needs_rebuild = True
                else:
                    # 구 unique(course_id, week_no) 가 남아 있으면 테이블 재구성
                    for idx in conn.execute(text("PRAGMA index_list(weeks)")).fetchall():
                        if not idx[2]:
                            continue
                        cols = [
                            c[2]
                            for c in conn.execute(text(f'PRAGMA index_info("{idx[1]}")')).fetchall()
                        ]
                        if cols == ["course_id", "week_no"]:
                            needs_rebuild = True
                            break
                if needs_rebuild:
                    conn.execute(text("PRAGMA foreign_keys=OFF"))
                    conn.execute(text("DROP TABLE IF EXISTS weeks_new"))
                    conn.execute(text(
                        """
                        CREATE TABLE weeks_new (
                            id VARCHAR(64) NOT NULL PRIMARY KEY,
                            course_id VARCHAR(64) NOT NULL,
                            week_no INTEGER NOT NULL,
                            session_no INTEGER DEFAULT 1 NOT NULL,
                            title VARCHAR(400) DEFAULT '',
                            week_title VARCHAR(400) DEFAULT '',
                            label VARCHAR(80) DEFAULT '',
                            created_at DATETIME,
                            updated_at DATETIME,
                            CONSTRAINT uq_course_week_session UNIQUE (course_id, week_no, session_no),
                            FOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE CASCADE
                        )
                        """
                    ))
                    has_session = "session_no" in week_cols
                    has_week_title = "week_title" in week_cols
                    sess_expr = "session_no" if has_session else "1"
                    wt_expr = "week_title" if has_week_title else "''"
                    conn.execute(text(
                        f"""
                        INSERT INTO weeks_new (
                            id, course_id, week_no, session_no, title, week_title, label, created_at, updated_at
                        )
                        SELECT id, course_id, week_no, {sess_expr}, title, {wt_expr}, label, created_at, updated_at
                        FROM weeks
                        """
                    ))
                    conn.execute(text("DROP TABLE weeks"))
                    conn.execute(text("ALTER TABLE weeks_new RENAME TO weeks"))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_weeks_course_id ON weeks (course_id)"
                    ))
                    conn.execute(text("PRAGMA foreign_keys=ON"))

    # 기존 overrides_json.sharedSetup → course_setups / course_page_rows
    from .course_setup_store import migrate_legacy_shared_setups

    db_mig = SessionLocal()
    try:
        n = migrate_legacy_shared_setups(db_mig)
        if n:
            print(f"migrated sharedSetup → tables: {n} course(s)")
    finally:
        db_mig.close()

    # ADMIN_USERNAMES 에 있는 계정 승격 + 관리자 0명이면 첫 유저를 관리자로
    from sqlalchemy import func, select

    from .models import User

    db = SessionLocal()
    try:
        names = settings.admin_name_set()
        if names:
            for u in db.scalars(select(User).where(User.username.in_(names))).all():
                if not u.is_admin:
                    u.is_admin = True
        n_admin = db.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(True))) or 0
        if n_admin == 0:
            first = db.scalars(select(User).order_by(User.id.asc())).first()
            if first:
                first.is_admin = True
        db.commit()
    finally:
        db.close()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
