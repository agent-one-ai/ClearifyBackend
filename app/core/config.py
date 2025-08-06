import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # Supabase
    SUPABASE_URL: str = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY")
    SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY")
    
    # Google OAuth
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:3000/auth/callback")
   
    # App
    SECRET_KEY: str = os.getenv("SECRET_KEY", "fallback-secret-key")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")
    PORT: int = int(os.getenv("PORT", 8000))
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    HOST: str = os.getenv("HOST", "127.0.0.1")
    API_KEY: str = os.getenv("API_KEY", "")

    # CORS
    ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        FRONTEND_URL
    ]

settings = Settings()