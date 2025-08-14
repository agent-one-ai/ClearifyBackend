from fastapi import APIRouter, HTTPException, Request
from fastapi.security import HTTPBearer
import logging
import time
from app.core.config import settings
from app.core.supabase_client import supabase_client
from app.schemas.prompts import Prompt
from app.core.logging import SupabaseAPILogger

router = APIRouter()
security = HTTPBearer()
api_logger = SupabaseAPILogger(supabase_client)

# Configurazione logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

from typing import List

@router.get("/prompts", response_model=List[Prompt])
async def get_prompts(request: Request):
    start_time = time.time()
    try:
        result = supabase_client.table("prompts").select("*").execute()
        prompts_data = result.data or []

        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            additional_data={"action": "get_prompts", "count": len(tones_data)}
        )

        return prompts_data

    except Exception as e:
        logger.exception("Error getting prompts")
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=str(e))
