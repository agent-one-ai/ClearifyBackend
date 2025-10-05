from typing import Optional
from app.core.config import settings
from app.core.analytics import AnalyticsDB
from app.services.email_service import EmailService
from datetime import datetime, date, timedelta
from app.schemas.analytics import DailyMetrics
import logging

logger = logging.getLogger(__name__)

class ReportGenerator:
    def __init__(self):
        self.db = AnalyticsDB()
        self.email_service = EmailService()
    
    async def generate_daily_report(self, target_date: Optional[date] = None, 
                                  send_email: bool = True) -> DailyMetrics:
        """Genera report giornaliero completo"""
        
        if target_date is None:
            target_date = date.today() - timedelta(days=1)  # Ieri
        
        logger.info(f"🔄 Generando report per {target_date}...")
        
        try:
            # Raccoglie metriche
            metrics = await self.db.get_daily_metrics(target_date)
            
            # Salva snapshot
            await self.db.save_daily_snapshot(metrics, target_date)
            
            # Invia email se richiesto
            if send_email:
                success = await self.email_service.send_daily_report(
                    metrics, 
                    settings.MAIN_MAIL
                )
                
                if success:
                    logger.info(f"✅ Report inviato a {settings.MAIN_MAIL}")
                else:
                    logger.info(f"❌ Errore invio email a {settings.MAIN_MAIL}")
            else:
                return metrics
            
            return success
            
        except Exception as e:
            logger.info(f"❌ Errore generazione report: {e}")
            
            # Log errore nel sistema
            error_log = {
                'event_type': 'error',
                'event_category': 'analytics',
                'message': f'Errore generazione report giornaliero: {str(e)}',
                'metadata': {'target_date': target_date.isoformat()},
                'severity': 3
            }
            
            self.db.supabase.table('system_events').insert(error_log).execute()
            return False