from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import logging
from datetime import datetime
from app.api.v1.endpoints import text_processing
from app.api.v1.endpoints import auth

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
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

# Include routers
app.include_router(
    text_processing.router,
    prefix="/api/v1/text",
    tags=["Text Processing"]
)

""" if settings.API_KEY:
    app.add_middleware(APIKeyMiddleware, api_key=settings.API_KEY)
 """
# Include routers
app.include_router(auth.router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": "1.0.0",
        "environment": settings.environment,
        "docs": "/docs" if settings.debug else None,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    try:
        return {
            "status": "healthy",
            "app_name": settings.app_name,
            "version": "1.0.0",
            "environment": settings.environment,
            "timestamp": datetime.utcnow().isoformat(),
            "services": {
                "redis": "connected" if settings.redis_url else "not configured",
                "openai": "configured" if settings.openai_api_key else "not configured"
            }
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "message": "Internal server error",
            "detail": str(exc) if os.getenv("DEBUG") == "true" else "Something went wrong"
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Global exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "message": "Internal server error",
            "detail": str(exc) if settings.debug else "Something went wrong",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# Startup event
@app.on_event("startup")
async def startup_event():
    logger.info(f"🚀 {settings.app_name} starting up...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    if settings.openai_api_key:
        logger.info("✅ OpenAI API configured")
    else:
        logger.warning("⚠️  OpenAI API key not configured")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"🛑 {settings.app_name} shutting down...")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.debug
    )
