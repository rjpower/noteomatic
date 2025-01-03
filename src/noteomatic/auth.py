from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from flask_login import UserMixin
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from noteomatic.config import settings

class User(UserMixin):
    def __init__(self, user_id: str, email: str, name: str):
        self.id = user_id
        self.email = email
        self.name = name
        
    @property
    def user_dir(self) -> Path:
        """Get the user's data directory"""
        return settings.users_dir / self.id
        
    @property
    def notes_dir(self) -> Path:
        """Get the user's notes directory"""
        return settings.notes_dir / self.id
        
    @property
    def raw_dir(self) -> Path:
        """Get the user's raw files directory"""
        return settings.raw_dir / self.id
        
    @property
    def build_dir(self) -> Path:
        """Get the user's build directory"""
        return settings.build_dir / self.id
    
    def init_directories(self):
        """Initialize user directories"""
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.build_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_google_oauth_flow() -> Flow:
        """Create Google OAuth flow"""
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=[
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
            ],
            redirect_uri=settings.google_oauth_redirect_uri,
        )
        return flow

    @classmethod
    def from_google_credentials(cls, credentials: Credentials) -> Optional[User]:
        """Create user from Google credentials"""
        try:
            service = build("oauth2", "v2", credentials=credentials)
            user_info = service.userinfo().get().execute()
            
            user = cls(
                user_id=user_info["id"],
                email=user_info["email"],
                name=user_info["name"],
            )
            user.init_directories()
            return user
        except Exception as e:
            print(f"Error creating user from Google credentials: {e}")
            return None

    def to_dict(self) -> dict:
        """Convert user to dictionary"""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional[User]:
        """Create user from dictionary"""
        if not all(k in data for k in ["id", "email", "name"]):
            return None
        user = cls(
            user_id=data["id"],
            email=data["email"],
            name=data["name"],
        )
        user.init_directories()
        return user
