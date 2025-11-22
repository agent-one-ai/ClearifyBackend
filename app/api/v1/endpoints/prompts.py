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
    try:
        result = supabase_client.table("prompts").select("*").execute()
        prompts_data = result.data or []

        return prompts_data

    except Exception as e:
        logger.exception("Error getting prompts")
        raise HTTPException(status_code=500, detail=str(e))
