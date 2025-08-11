from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api import auth
import os

# Create FastAPI app
app = FastAPI(
    title="Clearify API",
    description="Text humanization and improvement service",
    version="1.0.0",
    docs_url="/docs" if os.getenv("ENVIRONMENT") == "development" else None
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


""" if settings.API_KEY:
    app.add_middleware(APIKeyMiddleware, api_key=settings.API_KEY)
 """
# Include routers
app.include_router(auth.router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "message": "Welcome to Clearify API",
        "docs": "/docs" if os.getenv("ENVIRONMENT") == "development" else None
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "environment": os.getenv("ENVIRONMENT", "unknown"),
        "app_name": os.getenv("APP_NAME", "Clearify API")
    }

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "message": "Internal server error",
            "detail": str(exc) if os.getenv("DEBUG") == "true" else "Something went wrong"
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)