from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.staticfiles import StaticFiles
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
from app.api.v1.endpoints import support

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ================================
# UTILITY FUNCTIONS PER PROXY (DEFINITE PRIMA)
# ================================

#Funzione per rilevare se la richiesta arriva da nginx proxy, per controllare se la richiesta è sicura
def is_behind_proxy(request: Request) -> bool:
    """Rileva se la richiesta arriva da nginx proxy"""
    return (
        request.headers.get("x-forwarded-proto") == "https" or
        request.headers.get("x-forwarded-host") is not None or
        request.headers.get("x-real-ip") is not None
    )

#Funzione per ottenere l'IP reale del client considerando proxy headers
def get_client_ip(request):
    """Ottieni l'IP reale del client considerando proxy headers"""
    try:
        # Ottengo l'IP reale del client
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        #Ottengo a chi sta facendo la richiesta
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        if hasattr(request, 'client') and request.client:
            return request.client.host
        
        return "unknown"
    except Exception as e:
        logger.warning(f"Error getting client IP: {e}")
        return "unknown"

# Controllo se Redis è disponibile
try:
    redis_client = redis.Redis.from_url(settings.redis_url, db=1, decode_responses=True)
    redis_client.ping()
    redis_available = True
    logger.info("✅ Redis connected for rate limiting")
except Exception as e:
    redis_available = False
    logger.warning(f"⚠️  Redis not available for rate limiting: {e}")

# Se Redis è disponibile, creo il limiter
# Il limiter viene usato per limitare il numero di richieste per IP
if redis_available:
    limiter = Limiter(
        key_func=get_client_ip,
        storage_uri=f"{settings.redis_url}/1"
    )
else:
    # Se Redis non è disponibile, uso in-memory rate limiting (non è raccomandato per la produzione)
    limiter = Limiter(key_func=get_client_ip())
    logger.warning("⚠️  Using in-memory rate limiting (not recommended for production)")

# Instanzio l'app FastAPI e configuro le sue proprietà
app = FastAPI(
    title=settings.app_name,
    description="Clearify Backend",
    version="1.0.0"
)

# Registra il rate limiter nell'app
app.state.limiter = limiter

app.mount("/static", StaticFiles(directory="static"), name="static")

# Custom rate limit exception handler
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc: RateLimitExceeded):
    """Handler personalizzato per errori di rate limiting"""
    try:
        client_ip = get_client_ip(request)
        logger.warning(f"Rate limit exceeded for {client_ip}: {exc.detail}")
    except Exception:
        logger.warning(f"Rate limit exceeded: {exc.detail}")
    
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

# ================================
# CONFIGURAZIONE CORS PER NGINX PROXY HTTPS
# ================================

# Configurazione per proxy HTTPS - nginx gestisce CORS principale
frontend_url = os.getenv("FRONTEND_URL", "https://localhost:3000")
is_development = os.getenv("ENVIRONMENT", "development") == "development"

if is_development:
    # In sviluppo, includi sia nginx proxy che accesso diretto
    allowed_origins = [
        "https://localhost:3000",      # Frontend
        "https://localhost",           # Nginx proxy
        "http://localhost:3000",       # Fallback dev
        "https://127.0.0.1:3000",     # Alternative localhost
        "https://clearify.local",      # Custom domain
        frontend_url                   # Da environment
    ]
else:
    # In produzione, usa configurazione da settings
    cors_origins = os.getenv("CORS_ORIGINS", frontend_url)
    if isinstance(cors_origins, str):
        allowed_origins = [origin.strip() for origin in cors_origins.split(',')]
    else:
        allowed_origins = [frontend_url]


# ================================
# MIDDLEWARE PER NGINX PROXY
# ================================

@app.middleware("http")
async def proxy_headers_middleware(request: Request, call_next):
    """Middleware per gestire headers da nginx proxy"""
    
    try:
        response = await call_next(request)
        
        return response
        
    except Exception as e:
        logger.error(f"Proxy headers middleware error: {e}")
        # In caso di errore, continua comunque
        return await call_next(request)

# Global rate limiting per tutti gli endpoint
@app.middleware("http") 
async def rate_limit_middleware(request, call_next):
    """Middleware globale per rate limiting base"""
    try:
        # Rate limiting globale molto permissivo per endpoint non critici
        # Se la chiamata non è a uno dei seguenti endpoint, applica il rate limiting
        if not any(path in str(request.url) for path in ["/health", "/docs", "/openapi.json", "/"]):
            try:
                current_minute = datetime.utcnow().strftime("%Y%m%d%H%M")
                
                # Usa get_client_ip sicuro
                ip = get_client_ip(request)
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
                # Non bloccare la richiesta se il rate limiting fallisce
        
        response = await call_next(request)
        return response
        
    except Exception as e:
        logger.error(f"Rate limit middleware error: {e}")
        # In caso di errore critico, continua comunque con la richiesta
        try:
            return await call_next(request)
        except Exception as e2:
            logger.error(f"Critical middleware error: {e2}")
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error", "detail": "Middleware error"}
            )

# Vado a includere i routers che ho creato
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

app.include_router(
    support.router,
    prefix="/api/v1/support",
    tags=["Support"]
)

app.include_router(
    support.router,
    prefix="/api/v1",
    tags=["Support"]
)

@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": "1.0.0",
        "environment": settings.environment,
        "docs": "/docs" if settings.debug else None,
        "rate_limiting": "enabled" if redis_available else "memory_fallback",
        "cors_debug": os.getenv("DEBUG", "false").lower() == "true",
        "frontend_url": os.getenv("FRONTEND_URL"),
        "proxy_mode": "nginx-https",
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
                # Testo la connessione a Redis e controllo se è disponibile
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
            "proxy_config": {
                "mode": "nginx-https",
                "frontend_url": os.getenv("FRONTEND_URL"),
                "behind_proxy_expected": True,
                "debug_mode": os.getenv("DEBUG", "false").lower() == "true"
            },
            "cors_config": {
                "allowed_origins": allowed_origins if is_development else "configured",
                "credentials_enabled": True,
                "managed_by": "nginx only"
            },
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

@app.get("/api/v1/test-proxy")
async def test_proxy_setup(request: Request):
    """Test dell'integrazione nginx proxy + FastAPI"""
    
    try:
        headers = dict(request.headers)
        cookies = dict(request.cookies)
        behind_proxy = is_behind_proxy(request)
        client_ip = get_client_ip(request)
        
        analysis = {
            "proxy_analysis": {
                "behind_proxy": behind_proxy,
                "forwarded_proto": headers.get("x-forwarded-proto"),
                "forwarded_host": headers.get("x-forwarded-host"),
                "real_ip": headers.get("x-real-ip"),
                "client_ip": client_ip,
                "original_scheme": request.url.scheme,
                "original_host": headers.get("host")
            },
            "cookie_analysis": {
                "cookies_received": cookies,
                "cookie_count": len(cookies),
                "has_access_token": "access_token" in cookies,
                "has_refresh_token": "refresh_token" in cookies,
                "cookie_header": headers.get("cookie", "No cookie header")
            },
            "cors_analysis": {
                "origin": headers.get("origin"),
                "origin_allowed": headers.get("origin") in allowed_origins,
                "credentials_mode": "include" if request.headers.get("cookie") else "omit"
            },
            "configuration": {
                "frontend_url": os.getenv("FRONTEND_URL"),
                "environment": os.getenv("ENVIRONMENT"),
                "nginx_proxy_expected": True,
                "allowed_origins": allowed_origins,
                "debug_mode": os.getenv("DEBUG", "false").lower() == "true"
            },
            "recommendations": []
        }
        
        # Raccomandazioni automatiche
        if not behind_proxy:
            analysis["recommendations"].append("⚠️  Request not coming through nginx proxy")
            analysis["recommendations"].append("💡 Frontend should call https://localhost/api/ not http://localhost:8000/api/")
        
        if analysis["proxy_analysis"]["forwarded_proto"] == "https":
            analysis["recommendations"].append("✅ HTTPS forwarded correctly by nginx")
        
        if len(cookies) == 0:
            analysis["recommendations"].append("❌ No cookies received")
            analysis["recommendations"].append("💡 Check frontend uses credentials: 'include'")
        
        if behind_proxy and len(cookies) > 0:
            analysis["recommendations"].append("✅ Nginx proxy + cookies working correctly!")
        
        return analysis
    except Exception as e:
        logger.error(f"Test proxy error: {e}")
        return {"error": str(e), "status": "error"}

@app.get("/api/v1/metrics")
@limiter.limit("60/minute")
async def get_global_metrics(request):
    """Endpoint per metriche globali di rate limiting"""
    try:
        client_ip = get_client_ip(request)
        behind_proxy = is_behind_proxy(request)
        
        metrics = {
            "rate_limiting": {
                "status": "redis" if redis_available else "memory",
                "backend": settings.redis_url if redis_available else "in-memory"
            },
            "proxy_config": {
                "behind_nginx_proxy": behind_proxy,
                "client_ip": client_ip,
                "environment": os.getenv("ENVIRONMENT", "development"),
                "frontend_url": os.getenv("FRONTEND_URL"),
                "debug_mode": os.getenv("DEBUG", "false").lower() == "true"
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
    logger.info(f"Frontend URL: {os.getenv('FRONTEND_URL')}")
    logger.info(f"🔗 Nginx proxy mode: ENABLED")
    logger.info(f"CORS Debug: {os.getenv('DEBUG', 'false').lower() == 'true'}")
    
    if settings.openai_api_key:
        logger.info("✅ OpenAI API configured")
    else:
        logger.warning("⚠️  OpenAI API key not configured")
    
    if redis_available:
        logger.info("✅ Rate limiting with Redis enabled")
    else:
        logger.warning("⚠️  Using in-memory rate limiting")
    
    # Log configurazione CORS
    logger.info(f"✅ CORS fully managed by nginx")
    logger.info(f"🔗 Proxy headers detection: X-Forwarded-Proto, X-Real-IP, X-Forwarded-Host")
    if is_development:
        logger.info(f"🔧 Development allowed origins: {allowed_origins}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"🛑 {settings.app_name} shutting down...")
    
    if redis_available:
        try:
            redis_client.close()
            logger.info("✅ Redis connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")
