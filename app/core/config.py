import os
from dotenv import load_dotenv
from typing import Optional

# Importo il dotenv per la configurazione
load_dotenv()

class Settings:
    # App Setting
    app_name: str = os.getenv("APP_NAME")
    debug: bool = os.getenv("DEBUG")
    environment: str = os.getenv("ENVIRONMENT")

    # Indirizzi redis e celery per gestione dei task
    redis_url: str = os.getenv("REDIS_URL")
    celery_broker_url: str = os.getenv("CELERY_BROKER_URL")
    celery_result_backend: str = os.getenv("CELERY_RESULT_BACKEND")

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
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "")
    LOG_TO_FILE: str = os.getenv('LOG_TO_FILE', 'true')
    
    # Stripe
    STRIPE_PUBLIC_KEY: str = os.getenv("STRIPE_PUBLIC_KEY", "")
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")

    # Rate limiting
    rate_limit_requests: int = os.getenv("RATE_LIMIT_REQUESTS")
    rate_limit_window: int = os.getenv("RATE_LIMIT_WINDOW")

    # 📧 EMAIL CONFIGURATION
    # SMTP Server Settings
    EMAIL_HOST: str = os.getenv("EMAIL_HOST", "smtp.gmail.com")
    EMAIL_PORT: int = int(os.getenv("EMAIL_PORT", 587))
    EMAIL_HOST_USER: str = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD: str = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS: bool = os.getenv("EMAIL_USE_TLS", "true").lower() == "true"
    EMAIL_USE_SSL: bool = os.getenv("EMAIL_USE_SSL", "false").lower() == "true"
    
    # Sender Information
    EMAIL_FROM_NAME: str = os.getenv("EMAIL_FROM_NAME", "Clearify")
    EMAIL_FROM_EMAIL: str = os.getenv("EMAIL_FROM_EMAIL", os.getenv("EMAIL_HOST_USER", "noreply@clearify.com"))
    
    # Email Template Settings
    EMAIL_TEMPLATE_DIR: str = os.getenv("EMAIL_TEMPLATE_DIR", "templates/emails")
    
    # Email Behavior Settings
    EMAIL_TIMEOUT: int = int(os.getenv("EMAIL_TIMEOUT", 30))
    EMAIL_RETRY_ATTEMPTS: int = int(os.getenv("EMAIL_RETRY_ATTEMPTS", 3))
    EMAIL_RETRY_DELAY: int = int(os.getenv("EMAIL_RETRY_DELAY", 60))
    
    # Development/Testing Settings
    EMAIL_BACKEND: str = os.getenv("EMAIL_BACKEND", "smtp")  # smtp, console, file
    EMAIL_FILE_PATH: Optional[str] = os.getenv("EMAIL_FILE_PATH", None)
    EMAIL_CONSOLE_OUTPUT: bool = os.getenv("EMAIL_CONSOLE_OUTPUT", "false").lower() == "true"
    
    # Security Settings
    EMAIL_FAIL_SILENTLY: bool = os.getenv("EMAIL_FAIL_SILENTLY", "false").lower() == "true"
    EMAIL_RATE_LIMIT: int = int(os.getenv("EMAIL_RATE_LIMIT", 100))
    
    # Admin Email Settings
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", os.getenv("EMAIL_HOST_USER", "admin@clearify.com"))
    SUPPORT_EMAIL: str = os.getenv("SUPPORT_EMAIL", os.getenv("EMAIL_HOST_USER", "support@clearify.com"))
    MAIN_MAIL = str = os.getenv("MAIN_MAIL", "agentonesrl@gmail.com")
    
    cors_origins: str = f"http://localhost:3000,http://127.0.0.1:3000,{FRONTEND_URL}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    # CORS
    ALLOWED_ORIGINS = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        FRONTEND_URL
    ]

    # 🔥 PROPRIETÀ HELPER PER EMAIL
    @property
    def email_configured(self) -> bool:
        """Controlla se l'email è configurata correttamente"""
        return bool(self.EMAIL_HOST_USER and self.EMAIL_HOST_PASSWORD)

settings = Settings()