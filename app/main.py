from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
import os
import logging
import redis
from datetime import datetime

# Import routers
from app.api.v1.endpoints import text_processing
from app.api.v1.endpoints import auth
from app.api.v1.endpoints import frontend
from app.api.v1.endpoints import payments

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Rate Limiter Setup
def get_user_id_or_ip(request):
    """Funzione per identificare l'utente (IP se non autenticato)"""
    # TODO: Aggiorna quando implementi l'autenticazione completa
    # if hasattr(request.state, 'user') and request.state.user:
    #     return f"user_{request.state.user.id}"
    return get_remote_address(request)

# Setup Redis per rate limiting
try:
    redis_client = redis.Redis.from_url(settings.redis_url, db=1, decode_responses=True)
    redis_client.ping()
    redis_available = True
    logger.info("✅ Redis connected for rate limiting")
except Exception as e:
    redis_available = False
    logger.warning(f"⚠️  Redis not available for rate limiting: {e}")

# Crea limiter
if redis_available:
    limiter = Limiter(
        key_func=get_user_id_or_ip,
        storage_uri=f"{settings.redis_url}/1"  # Database 1 per rate limiting
    )
else:
    # Fallback a memory storage se Redis non è disponibile
    limiter = Limiter(key_func=get_user_id_or_ip)
    logger.warning("⚠️  Using in-memory rate limiting (not recommended for production)")

# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="Text humanization and improvement service with rate limiting",
    version="1.0.0",
    docs_url="/docs" if os.getenv("ENVIRONMENT") == "development" else None
)

# Registra il rate limiter nell'app
app.state.limiter = limiter

# Custom rate limit exception handler
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc: RateLimitExceeded):
    """Handler personalizzato per errori di rate limiting"""
    logger.warning(f"Rate limit exceeded for {get_user_id_or_ip(request)}: {exc.detail}")
    
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "message": f"Too many requests. {exc.detail}",
            "retry_after": getattr(exc, 'retry_after', 60),
            "type": "rate_limit_error",
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers con rate limiting
app.include_router(
    text_processing.router,
    prefix="/api/v1/text",
    tags=["Text Processing"]
)

app.include_router(
    payments.router,
    prefix="/api/v1/payments", 
    tags=["Payment Processing"]
)

app.include_router(
    frontend.router,
    prefix="/api/v1/frontend",
    tags=["Frontend"]
)

app.include_router(auth.router, prefix="/api/v1")

# Global rate limiting per tutti gli endpoint non specificati
@app.middleware("http")
async def rate_limit_middleware(request, call_next):
    """Middleware globale per rate limiting base"""
    try:
        # Rate limiting globale molto permissivo per endpoint non critici
        if not any(path in str(request.url) for path in ["/health", "/docs", "/openapi.json", "/"]):
            # Applica un rate limit base di 300 req/min per IP
            try:
                current_minute = datetime.utcnow().strftime("%Y%m%d%H%M")
                ip = get_remote_address(request)
                key = f"global_rate_limit:{ip}:{current_minute}"
                
                if redis_available:
                    current_count = redis_client.get(key) or 0
                    if int(current_count) >= 300:  # 300 req/min limite globale
                        return JSONResponse(
                            status_code=429,
                            content={
                                "error": "Global rate limit exceeded", 
                                "message": "Too many requests from this IP",
                                "retry_after": 60
                            }
                        )
                    redis_client.incr(key)
                    redis_client.expire(key, 60)
            except Exception as e:
                logger.warning(f"Rate limit middleware error: {e}")
        
        response = await call_next(request)
        return response
        
    except Exception as e:
        logger.error(f"Middleware error: {e}")
        return await call_next(request)

@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": "1.0.0",
        "environment": settings.environment,
        "docs": "/docs" if settings.debug else None,
        "rate_limiting": "enabled" if redis_available else "memory_fallback",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/health")
async def health_check():
    try:
        # Test Redis connection
        redis_status = "connected"
        openai_usage = {}
        
        if redis_available:
            try:
                redis_client.ping()
                
                # Check current OpenAI usage
                current_minute = datetime.utcnow().strftime("%Y%m%d%H%M")
                current_rpm = int(redis_client.get(f"openai:rpm:{current_minute}") or 0)
                current_tpm = int(redis_client.get(f"openai:tpm:{current_minute}") or 0)
                
                openai_usage = {
                    "current_rpm": current_rpm,
                    "current_tpm": current_tpm,
                    "rpm_limit": 450,
                    "tpm_limit": 80000,
                    "rpm_usage_percent": round((current_rpm / 450) * 100, 2),
                    "tpm_usage_percent": round((current_tpm / 80000) * 100, 2)
                }
            except Exception as e:
                redis_status = f"error: {str(e)}"
        else:
            redis_status = "not configured"
        
        return {
            "status": "healthy",
            "app_name": settings.app_name,
            "version": "1.0.0",
            "environment": settings.environment,
            "timestamp": datetime.utcnow().isoformat(),
            "services": {
                "redis": redis_status,
                "openai": "configured" if settings.openai_api_key else "not configured",
                "rate_limiting": "redis" if redis_available else "memory"
            },
            "openai_usage": openai_usage
        }
        
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.get("/api/v1/metrics")
@limiter.limit("60/minute")
async def get_global_metrics(request):
    """Endpoint per metriche globali di rate limiting"""
    try:
        metrics = {
            "rate_limiting": {
                "status": "redis" if redis_available else "memory",
                "backend": settings.redis_url if redis_available else "in-memory"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if redis_available:
            current_minute = datetime.utcnow().strftime("%Y%m%d%H%M")
            
            # Metriche OpenAI
            openai_rpm = int(redis_client.get(f"openai:rpm:{current_minute}") or 0)
            openai_tpm = int(redis_client.get(f"openai:tpm:{current_minute}") or 0)
            
            metrics["openai"] = {
                "requests_per_minute": openai_rpm,
                "tokens_per_minute": openai_tpm,
                "rpm_limit": 450,
                "tpm_limit": 80000,
                "rpm_usage_percent": round((openai_rpm / 450) * 100, 2),
                "tpm_usage_percent": round((openai_tpm / 80000) * 100, 2)
            }
            
            # Top IPs per rate limiting
            ip_keys = redis_client.keys(f"global_rate_limit:*:{current_minute}")
            top_ips = []
            for key in ip_keys[:10]:  # Top 10 IPs
                ip = key.split(':')[1]
                count = int(redis_client.get(key) or 0)
                top_ips.append({"ip": ip, "requests": count})
            
            metrics["top_requesting_ips"] = sorted(top_ips, key=lambda x: x["requests"], reverse=True)
        
        return metrics
        
    except Exception as e:
        logger.error(f"Failed to get global metrics: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get metrics: {str(e)}"
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
    
    if redis_available:
        logger.info("✅ Rate limiting with Redis enabled")
    else:
        logger.warning("⚠️  Using in-memory rate limiting")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"🛑 {settings.app_name} shutting down...")
    
    if redis_available:
        try:
            redis_client.close()
            logger.info("✅ Redis connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.debug
    )