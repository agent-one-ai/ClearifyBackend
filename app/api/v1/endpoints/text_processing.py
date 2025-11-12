from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from typing import Dict, Any
import uuid
import logging
import redis
from datetime import datetime, timedelta
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.schemas.text_schemas import (
    TextProcessingRequest,
    TextProcessingResponse,
    TaskStatusResponse,
    TaskStatus,
    ProcessedTextResult
)
from app.workers.tasks import process_text_task
from app.core.celery_app import celery_app
from app.services.openai_service import openai_service
from app.core.config import settings
from app.core.auth import get_authenticated_user_with_credits, verify_email_verified
from app.core.supabase_client import supabase_client

logger = logging.getLogger(__name__)
router = APIRouter()

# Setup Redis client per rate limiting
try:
    redis_client = redis.Redis.from_url(settings.redis_url, db=1, decode_responses=True)
    redis_available = True
except Exception as e:
    redis_available = False
    logger.warning(f"Redis not available for OpenAI rate limiting: {e}")

# ================================
# FUNZIONI SICURE PER RATE LIMITING
# ================================

def get_client_ip_safe(request: Request) -> str:
    """Ottieni l'IP reale del client in modo sicuro"""
    try:
        # Priorità: X-Real-IP (nginx) > X-Forwarded-For > remote address
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        if hasattr(request, 'client') and request.client:
            return request.client.host
        
        return "unknown"
    except Exception as e:
        logger.warning(f"Error getting client IP: {e}")
        return "unknown"

def get_user_id_or_ip_safe(request: Request):
    """Funzione sicura per identificare l'utente"""
    try:
        # TODO: Aggiorna quando implementi l'autenticazione completa
        if hasattr(request.state, 'user') and request.state.user:
             return f"user_{request.state.user.id}"
        
        return get_client_ip_safe(request)
    except Exception as e:
        logger.warning(f"Error in get_user_id_or_ip_safe: {e}")
        try:
            return get_remote_address(request)
        except Exception:
            return "unknown"

def get_global_key(request: Request):
    """Chiave globale per rate limiting OpenAI"""
    return "openai_global"

# ================================
# FUNZIONI OPENAI QUOTA (INVARIATE)
# ================================

async def check_openai_quota() -> tuple[bool, dict]:
    """
    Controlla se possiamo fare una chiamata OpenAI
    Returns: (can_proceed, quota_info)
    """
    if not redis_available:
        return True, {"status": "redis_unavailable"}
    
    try:
        current_minute = datetime.utcnow().strftime("%Y%m%d%H%M")
        
        # Chiavi Redis per tracking
        rpm_key = f"openai:rpm:{current_minute}"
        tpm_key = f"openai:tpm:{current_minute}"
        
        # Recupera contatori attuali
        current_rpm = int(redis_client.get(rpm_key) or 0)
        current_tpm = int(redis_client.get(tpm_key) or 0)
        
        # Limiti conservativi (adatta ai tuoi tier OpenAI)
        MAX_RPM = 450  # Sotto il limite di 500 per sicurezza
        MAX_TPM = 80000  # Sotto il limite di 90k per sicurezza
        
        quota_info = {
            "current_rpm": current_rpm,
            "current_tpm": current_tpm,
            "max_rpm": MAX_RPM,
            "max_tpm": MAX_TPM,
            "rpm_usage_percent": round((current_rpm / MAX_RPM) * 100, 2),
            "tpm_usage_percent": round((current_tpm / MAX_TPM) * 100, 2)
        }
        
        # Controlla se possiamo fare la richiesta
        if current_rpm >= MAX_RPM:
            logger.warning(f"OpenAI RPM limit reached: {current_rpm}/{MAX_RPM}")
            return False, quota_info
            
        if current_tpm >= MAX_TPM:
            logger.warning(f"OpenAI TPM limit reached: {current_tpm}/{MAX_TPM}")
            return False, quota_info
            
        return True, quota_info
        
    except Exception as e:
        logger.error(f"Error checking OpenAI quota: {e}")
        return True, {"status": "error", "message": str(e)}

async def track_openai_usage(estimated_tokens: int = 1000):
    """Traccia l'utilizzo OpenAI in Redis"""
    if not redis_available:
        return
        
    try:
        current_minute = datetime.utcnow().strftime("%Y%m%d%H%M")
        
        # Incrementa contatori
        rpm_key = f"openai:rpm:{current_minute}"
        tpm_key = f"openai:tpm:{current_minute}"
        
        # Incrementa RPM
        redis_client.incr(rpm_key)
        redis_client.expire(rpm_key, 60)  # Scade dopo 1 minuto
        
        # Incrementa TPM (stima)
        redis_client.incrby(tpm_key, estimated_tokens)
        redis_client.expire(tpm_key, 60)
        
        logger.info(f"OpenAI usage tracked: +1 request, +{estimated_tokens} tokens")
        
    except Exception as e:
        logger.error(f"Error tracking OpenAI usage: {e}")

def estimate_tokens(text: str) -> int:
    """Stima approssimativa dei token per il testo"""
    # Stima: 1 token ≈ 0.75 parole in inglese, un po' più in italiano
    words = len(text.split())
    estimated_tokens = int(words * 1.3)  # Moltiplicatore conservativo

    # Token minimi e massimi ragionevoli
    return max(50, min(estimated_tokens, 4000))

def count_words(text: str) -> int:
    """
    Conta il numero di parole nel testo
    Rimuove spazi multipli e conta solo parole valide
    """
    if not text or not text.strip():
        return 0

    # Rimuovi spazi multipli e split
    words = text.strip().split()

    # Conta solo parole non vuote
    return len([word for word in words if word.strip()])

# ================================
# RATE LIMITING SICURO
# ================================

def get_limiter(request: Request):
    """Ottieni il limiter dall'app state in modo sicuro"""
    try:
        return request.app.state.limiter
    except Exception as e:
        logger.warning(f"Could not get limiter from app state: {e}")
        return None

async def apply_rate_limit_safe(request: Request, limit: str, key_func=None):
    """Applica rate limiting in modo sicuro"""
    try:
        limiter = get_limiter(request)
        if limiter:
            if key_func:
                await limiter.limit(limit, key_func=key_func)(request)
            else:
                await limiter.limit(limit)(request)
    except Exception as e:
        logger.warning(f"Rate limiting failed: {e}")
        # Non bloccare la richiesta se il rate limiting fallisce

# ================================
# ENDPOINTS AGGIORNATI
# ================================

@router.post("/process", response_model=TextProcessingResponse)
async def process_text(
    request: TextProcessingRequest,
    fastapi_request: Request,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_authenticated_user_with_credits)  # ✅ AUTENTICAZIONE ABILITATA
):
    """
    Start text processing task with JWT authentication and subscription verification

    Requires:
    - Valid JWT token (httpOnly cookie)
    - Verified email address
    - Available credits (for free tier users)
    """
    try:
        user_id = user.get("id")
        user_email = user.get("email")
        subscription_tier = user.get("subscription_tier", "free")
        credits_remaining = user.get("credits_remaining", 0)

        # ✅ CONTA PAROLE NEL TESTO
        word_count = count_words(request.text)
        logger.info(f"Word count for request: {word_count} words")

        # ✅ RATE LIMITING DIFFERENZIATO PER TIER
        if subscription_tier == "free":
            # Free: 30 req/hour, max 200 parole per richiesta
            await apply_rate_limit_safe(fastapi_request, "30/hour")
            max_words_per_request = 200
            max_text_length = 10000  # Mantieni anche limite caratteri per sicurezza
        else:
            # Premium: 500 req/hour, max 1000 parole per richiesta
            await apply_rate_limit_safe(fastapi_request, "500/hour")
            max_words_per_request = 1000
            max_text_length = 50000

        # ✅ VERIFICA LIMITE PAROLE PER TIER
        if word_count > max_words_per_request:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "TEXT_TOO_LONG",
                    "message": f"Text exceeds maximum word limit for {subscription_tier} tier",
                    "max_words": max_words_per_request,
                    "current_words": word_count,
                    "subscription_tier": subscription_tier
                }
            )

        # Verifica lunghezza caratteri per tier (sicurezza aggiuntiva)
        if len(request.text) > max_text_length:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "TEXT_TOO_LONG",
                    "message": f"Text exceeds maximum character length for {subscription_tier} tier",
                    "max_length": max_text_length,
                    "current_length": len(request.text),
                    "subscription_tier": subscription_tier
                }
            )

        # ✅ VERIFICA CREDITI SUFFICIENTI PER FREE USERS (1 credito per processo)
        if subscription_tier == "free":
            if credits_remaining < 1:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "INSUFFICIENT_CREDITS",
                        "message": f"Insufficient credits. You need at least 1 credit to process text.",
                        "credits_remaining": credits_remaining,
                        "subscription_tier": subscription_tier
                    }
                )

        # Rate limiting globale OpenAI
        await apply_rate_limit_safe(fastapi_request, "200/minute", key_func=get_global_key)

        # Stima token prima del controllo quota
        estimated_tokens = estimate_tokens(request.text)

        # Controlla quota OpenAI prima di procedere
        can_proceed, quota_info = await check_openai_quota()

        if not can_proceed:
            logger.warning(f"OpenAI quota exceeded: {quota_info}")
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate limit",
                    "message": "API quota temporarily exceeded. Please try again in a moment.",
                    "retry_after": 60,
                    "quota_info": quota_info,
                    "type": "openai_quota_exceeded"
                }
            )

        # Generate task ID
        task_id = str(uuid.uuid4())

        # Traccia l'utilizzo prima della chiamata
        await track_openai_usage(estimated_tokens)

        # Get text analysis for estimated completion time
        try:
            analysis = await openai_service.get_text_analysis(request.text)
        except Exception as openai_error:
            logger.error(f"OpenAI service error: {openai_error}")
            analysis = {
                "estimated_processing_time": 30,
                "complexity": "medium"
            }

        estimated_completion = datetime.utcnow().replace(microsecond=0) + \
                             timedelta(seconds=analysis["estimated_processing_time"])

        # ✅ DECREMENTA CREDITI PER FREE USERS (1 credito per processo)
        if subscription_tier == "free" and credits_remaining >= 1:
            new_credits = credits_remaining - 1
            supabase_client.table("users").update({
                "credits_remaining": new_credits
            }).eq("id", user_id).execute()

            logger.info(f"Credits decremented for user {user_email}: {credits_remaining} -> {new_credits} (1 credit for process, {word_count} words)")

        # Start Celery task con retry policy
        task = process_text_task.apply_async(
            args=[
                request.text,
                request.processing_type.value,
                user_id,  # ✅ Usa user_id autenticato invece di request.user_id
                request.options
            ],
            task_id=task_id,
            queue="text_processing",
            retry_policy={
                'max_retries': 3,
                'interval_start': 5,
                'interval_step': 10,
                'interval_max': 60,
            }
        )

        # Log metrics per monitoring
        credits_after = credits_remaining - 1 if subscription_tier == "free" else "unlimited"
        logger.info(
            f"✅ Text processing started - Task: {task_id}, "
            f"User: {user_email} ({subscription_tier}), "
            f"Word count: {word_count}, "
            f"Text length: {len(request.text)} chars, "
            f"Est. tokens: {estimated_tokens}, "
            f"Credits remaining: {credits_after}, "
            f"OpenAI usage: {quota_info.get('rpm_usage_percent', 0):.1f}% RPM"
        )

        return TextProcessingResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message=f"Text processing started. Estimated completion in {analysis['estimated_processing_time']} seconds.",
            estimated_completion=estimated_completion
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start text processing task: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start text processing: {str(e)}"
        )

@router.get("/task/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    fastapi_request: Request,
    user: dict = Depends(verify_email_verified)  # ✅ Solo email verificata (non serve check crediti)
):
    """
    Get status of a text processing task
    Requires authentication (no credit check needed - task already created)
    """
    try:
        # Rate limiting più permissivo per status check
        await apply_rate_limit_safe(fastapi_request, "120/minute")
        
        # Get task result from Celery
        result = celery_app.AsyncResult(task_id)
        
        if not result:
            raise HTTPException(
                status_code=404,
                detail="Task not found"
            )
        
        # Map Celery states to our TaskStatus
        status_mapping = {
            "PENDING": TaskStatus.PENDING,
            "PROCESSING": TaskStatus.PROCESSING,
            "SUCCESS": TaskStatus.COMPLETED,
            "FAILURE": TaskStatus.FAILED,
            "RETRY": TaskStatus.PROCESSING,
            "REVOKED": TaskStatus.FAILED
        }
        
        status = status_mapping.get(result.state, TaskStatus.PENDING)
        
        # Get additional info from task meta
        task_info = result.info or {}
        
        response_data = {
            "task_id": task_id,
            "status": status,
            "created_at": datetime.utcnow(),  # You might want to store this when creating tasks
            "updated_at": datetime.utcnow(),
            "progress": task_info.get("progress", 0 if status == TaskStatus.PENDING else 100),
        }
        
        # Add result if completed
        if status == TaskStatus.COMPLETED and "result" in task_info:
            response_data["result"] = task_info["result"]["processed_text"]
        
        # Add error if failed
        if status == TaskStatus.FAILED:
            response_data["error"] = task_info.get("error", str(result.info) if result.info else "Unknown error")
        
        return TaskStatusResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task status for {task_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get task status: {str(e)}"
        )

@router.get("/task/{task_id}/result", response_model=ProcessedTextResult)
async def get_task_result(
    task_id: str,
    fastapi_request: Request,
    user: dict = Depends(verify_email_verified)  # ✅ Solo email verificata (non serve check crediti)
):
    """
    Get detailed result of a completed text processing task
    Requires authentication (no credit check needed - task already created)
    """
    try:
        await apply_rate_limit_safe(fastapi_request, "60/minute")
        
        result = celery_app.AsyncResult(task_id)
        
        if not result:
            raise HTTPException(status_code=404, detail="Task not found")
        
        if result.state != "SUCCESS":
            raise HTTPException(
                status_code=400,
                detail=f"Task is not completed yet. Current status: {result.state}"
            )
        
        task_result = result.info.get("result")
        if not task_result:
            raise HTTPException(status_code=404, detail="Task result not found")
        
        return ProcessedTextResult(**task_result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task result for {task_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get task result: {str(e)}"
        )

@router.delete("/task/{task_id}")
async def cancel_task(
    task_id: str,
    fastapi_request: Request,
    user: dict = Depends(get_authenticated_user_with_credits)  # ✅ AUTENTICAZIONE ABILITATA
):
    """
    Cancel a pending or running task
    Requires authentication
    """
    try:
        await apply_rate_limit_safe(fastapi_request, "20/minute")
        
        celery_app.control.revoke(task_id, terminate=True)
        
        logger.info(f"Task cancelled: {task_id}")
        
        return {
            "message": f"Task {task_id} has been cancelled",
            "task_id": task_id,
            "status": "cancelled"
        }
        
    except Exception as e:
        logger.error(f"Failed to cancel task {task_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel task: {str(e)}"
        )

@router.get("/health")
async def health_check():
    """
    Health check endpoint for text processing service
    """
    try:
        # Test Celery connection
        inspector = celery_app.control.inspect()
        active_tasks = inspector.active()
        
        # Test OpenAI service
        openai_status = "ok" if openai_service else "not configured"
        
        # Check Redis connection
        redis_status = "ok" if redis_available else "not configured"
        if redis_available:
            try:
                redis_client.ping()
            except Exception:
                redis_status = "error"
        
        # Check current OpenAI usage
        quota_info = {}
        if redis_available:
            try:
                current_minute = datetime.utcnow().strftime("%Y%m%d%H%M")
                current_rpm = int(redis_client.get(f"openai:rpm:{current_minute}") or 0)
                current_tpm = int(redis_client.get(f"openai:tpm:{current_minute}") or 0)
                
                quota_info = {
                    "current_rpm": current_rpm,
                    "current_tpm": current_tpm,
                    "rpm_limit": 450,
                    "tpm_limit": 80000,
                    "rpm_usage_percent": round((current_rpm / 450) * 100, 2),
                    "tpm_usage_percent": round((current_tpm / 80000) * 100, 2)
                }
            except Exception as e:
                quota_info = {"error": str(e)}
        
        return {
            "status": "healthy",
            "celery_workers": len(active_tasks) if active_tasks else 0,
            "openai_service": openai_status,
            "redis_status": redis_status,
            "openai_usage": quota_info,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }