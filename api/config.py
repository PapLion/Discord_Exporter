import os
from pydantic import BaseSettings
from typing import List, Optional

class Settings(BaseSettings):
    # API settings
    API_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Discord Exporter API"
    VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    
    # CORS settings
    BACKEND_CORS_ORIGINS: List[str] = ["*"]
    
    # Security
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8  # 8 days
    
    # File storage
    EXPORT_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exports")
    MAX_EXPORT_SIZE_MB: int = 100  # Maximum size of exported data in MB
    
    # Rate limiting
    RATE_LIMIT: str = "1000/day;100/hour;10/minute"
    
    class Config:
        case_sensitive = True
        env_file = ".env"

settings = Settings()
