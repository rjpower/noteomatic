from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    """Database configuration settings"""

    sqlite_wal: bool = True
    sqlite_timeout: float = 30.0


class AppSettings(BaseSettings):
    """Application configuration settings"""
    model_config = SettingsConfigDict(
        env_prefix="NOTEOMATIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="_",
    )

    db: DatabaseSettings = DatabaseSettings()

    root_dir: Path = Path(__file__).parent.parent.parent
    scp_target: str = Field(
        default="user@example.com:/var/www/html/shared",
        description="SCP target for sharing notes",
    )
    gemini_api_key: str = ""
    
    # Google OAuth settings
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:5000/login/callback"
    
    # User data settings
    users_dir: Path = root_dir / "users"
    public_share_url: str = ""
    build_dir: Path = root_dir / "build"
    raw_dir: Path = root_dir / "raw"
    notes_dir: Path = build_dir / "notes"
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    @property
    def static_dir(self) -> Path:
        return self.root_dir / "static"

    @property
    def template_dir(self) -> Path:
        return Path(__file__).parent / "templates"

settings = AppSettings()
