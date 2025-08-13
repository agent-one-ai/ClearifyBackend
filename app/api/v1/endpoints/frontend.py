from fastapi import APIRouter, HTTPException, Request
from fastapi.security import HTTPBearer
import logging
import time
from app.core.config import settings
from app.core.supabase_client import supabase_client
from app.schemas.frontend import Tone, ContentTemplate
from app.core.logging import SupabaseAPILogger

router = APIRouter()
security = HTTPBearer()
api_logger = SupabaseAPILogger(supabase_client)

# Configurazione logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

from typing import List

@router.get("/tones", response_model=List[Tone])
async def get_tones(request: Request):
    start_time = time.time()
    try:
        result = supabase_client.table("tones").select("*").execute()
        tones_data = result.data or []

        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            additional_data={"action": "get_tones", "count": len(tones_data)}
        )

        return tones_data

    except Exception as e:
        logger.exception("Error getting tones")
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/templates", response_model=List[ContentTemplate])
async def get_templates(request: Request):
    start_time = time.time()
    try:
        result = supabase_client.table("templates").select("*").execute()
        templates_data = result.data or []

        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            additional_data={"action": "get_templates", "count": len(templates_data)}
        )

        return templates_data

    except Exception as e:
        logger.exception("Error getting templates")
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))
