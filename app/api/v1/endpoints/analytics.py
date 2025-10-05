from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
import logging
import time
from app.core.config import settings
from app.core.supabase_client import supabase_client
from app.schemas.frontend import Tone, ContentTemplate
from app.core.logging import SupabaseAPILogger
from datetime import date
from app.core.report_generator import ReportGenerator
from app.schemas.analytics import DailyMetrics
import asyncio
from app.core.analytics import AnalyticsDB

router = APIRouter()
security = HTTPBearer()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

@router.get("/get_analytics/{date}")
def get_analytics(date: date):
    """
    Endpoint per ricevere le analytics del giorno
    """
    try:                
        analytics = ReportGenerator()
    
        result = asyncio.run(
            analytics.generate_daily_report(target_date=date, send_email=False)
        )

        return result
        
    except Exception as e:
        logger.error(f"Error checking analytics: {str(e)}")
        raise HTTPException(status_code=500, detail="Error checking analytics")