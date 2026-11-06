from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "TRINETRA"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # Database (SQLite for easy local run, switch to PostgreSQL in production)
    DATABASE_URL: str = "sqlite:///./trinetra.db"
    # DATABASE_URL: str = "postgresql://trinetra:trinetra@localhost:5432/trinetra"
    
    SECRET_KEY: str = "trinetra-dev-secret-change-in-production-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours
    
    # Booking
    HOLD_TTL_MINUTES: int = 5
    DEFAULT_TIMEZONE: str = "Asia/Kolkata"
    
    # Gemini AI
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

@lru_cache()
def get_settings():
    return Settings()
