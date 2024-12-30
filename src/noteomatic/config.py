from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    """Database configuration settings"""

    driver: str = "postgresql+psycopg"
    user: str = "postgres"
    password: str = "postgres"
    host: str = "localhost"
    port: int = 5432
    name: str = "noteomatic"
    url: Optional[str] = None
    sqlite_wal: bool = True
    sqlite_timeout: float = 30.0
    pool_size: int = 5
    max_overflow: int = 10

    def get_url(self) -> str:
        """Generate SQLAlchemy database URL"""
        if self.url:
            return self.url

        if self.driver.startswith("sqlite"):
            return f"{self.driver}:///{self.name}"
            
        return (
            f"{self.driver}://{self.user}:{self.password}@"
            f"{self.host}:{self.port}/{self.name}"
        )


class AppSettings(BaseSettings):
    """Application configuration settings"""
    model_config = SettingsConfigDict(
        env_prefix="NOTEOMATIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="_",
    )

    db: DatabaseSettings

    root_dir: Path = Path(__file__).parent.parent.parent
    scp_target: str = Field(
        default="user@example.com:/var/www/html/shared",
        description="SCP target for sharing notes",
    )
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
