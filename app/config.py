from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DEFAULT_DB = DATA_DIR / "learningflow.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = f"sqlite:///{DEFAULT_DB.as_posix()}"
    app_password: str = "change-me"  # 레거시(공유 비번). 계정 로그인 우선.
    session_secret: str = "lf-dev-session-secret-change-me"
    # 콤마 구분. 예: admin,kikiy  — 해당 아이디는 관리자
    admin_usernames: str = "admin"
    usd_krw: float = 1350.0
    anthropic_api_key: str = ""
    host: str = "127.0.0.1"
    port: int = 8000

    def admin_name_set(self) -> set[str]:
        return {x.strip() for x in (self.admin_usernames or "").split(",") if x.strip()}


settings = Settings()
