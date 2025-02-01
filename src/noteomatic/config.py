from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application configuration settings"""
    model_config = SettingsConfigDict(
        env_prefix="NOTEOMATIC_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="_",
    )

    root_dir: Path = Path(__file__).parent.parent.parent
    scp_target: str = Field(
        default="user@example.com:/var/www/html/shared",
        description="SCP target for sharing notes",
    )
    gemini_api_key: str = ""

    public_share_url: str = ""
    build_dir: Path = root_dir / "build"
    raw_dir: Path = root_dir / "raw"
    notes_dir: Path = build_dir / "notes"
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

settings = AppSettings()
