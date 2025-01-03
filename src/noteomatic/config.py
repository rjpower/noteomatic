import secrets
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator
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
    gemini_api_key: str = Field(..., description="Google Gemini API key")
    
    # Google OAuth settings
    google_client_id: str = Field(..., description="Google OAuth client ID")
    google_client_secret: str = Field(..., description="Google OAuth client secret")
    google_oauth_redirect_uri: str = Field(
        default="http://localhost:5000/login/callback",
        description="Google OAuth redirect URI"
    )
    
    # Flask settings
    secret_key: str = Field(
        default_factory=lambda: secrets.token_hex(32),
        description="Flask secret key for sessions"
    )
    
    # User data settings
    public_share_url: str = ""
    build_dir: Path = root_dir / "build"
    raw_dir: Path = root_dir / "raw"
    notes_dir: Path = build_dir / "notes"
    users_dir: Path = notes_dir / "users"  # Store user data under notes directory
    debug: bool = Field(default=False, description="Enable debug mode")
    log_level: str = Field(default="INFO", description="Logging level")

    @property
    def static_dir(self) -> Path:
        return self.root_dir / "static"

    @property
    def template_dir(self) -> Path:
        return Path(__file__).parent / "templates"

    @field_validator('google_client_id', 'google_client_secret', 'gemini_api_key')
    @classmethod
    def validate_required_keys(cls, value: str, info) -> str:
        """Validate that required API keys and secrets are provided"""
        if not value:
            raise ValueError(
                f"{info.field_name} is required. Please set {info.field_name} in your environment "
                f"or .env file."
            )
        return value

try:
    settings = AppSettings()
except Exception as e:
    print("\nError loading configuration from src/noteomatic/config.py:")
    print("=" * 80)
    print(str(e))
    print("\nPlease ensure all required environment variables are set in your .env file")
    print("or environment. See src/noteomatic/config.py for all options.")
    print("\nRequired variables:")
    print("- NOTEOMATIC_GOOGLE_CLIENT_ID: Google OAuth client ID")
    print("- NOTEOMATIC_GOOGLE_CLIENT_SECRET: Google OAuth client secret") 
    print("- NOTEOMATIC_GEMINI_API_KEY: Google Gemini API key")
    print("\nYou can set these in:")
    print("1. A .env file in the project root")
    print("2. Your environment variables")
    print("\nSee README.md for more configuration details.")
    print("=" * 80)
    raise SystemExit(1)
