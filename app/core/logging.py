import logging
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import Request, Response
from supabase import Client
import traceback
from app.core.supabase_client import supabase_client

logger = logging.getLogger("clearify-api")

class SupabaseAPILogger:
    def __init__(self, supabase_client: Client):
        self.supabase = supabase_client
    
    async def log_api_call(
        self,
        request: Request,
        response: Optional[Response] = None,
        response_time: Optional[float] = None,
        user_id: Optional[str] = None,
        error: Optional[str] = None,
        additional_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        endpoint: Optional[str] = None
    ):
        """
        Logga una chiamata API nella tabella usage_logs di Supabase
        """
        try:
            client_ip = None
            user_agent = None
            query_params = None
            
            if user_email is None:
                # Estrai informazioni dalla richiesta
                client_ip = self._get_client_ip(request)
                method = request.method
                endpoint = str(request.url.path)
                query_params = dict(request.query_params) if request.query_params else None
                user_agent = request.headers.get("User-Agent", "Unknown")
            else:
                method = 'POST'

            # Prepara i dati per il log
            log_data = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat(),
                "client_ip": client_ip if client_ip else None,
                "method": method,
                "endpoint": endpoint,
                "query_params": json.dumps(query_params) if query_params else None,
                "user_agent": user_agent if user_agent else None,
                "user_id": user_id,
                "response_time_ms": response_time,
                "status_code": response.status_code if response else None,
                "error_message": error,
                "additional_data": json.dumps(additional_data) if additional_data else None,
                "created_at": datetime.utcnow().isoformat(),
                "user_email": user_email
            }
            
            # Inserisci nel database
            result = self.supabase.table("usage_logs").insert(log_data).execute()
            
            if not result.data:
                logger.error("Errore nell'inserimento del log in Supabase")
            
        except Exception as e:
            # Non interrompere l'API se il logging fallisce
            logger.error(f"Errore nel logging API: {str(e)}")
            logger.error(traceback.format_exc())
    
    async def log_security_event(
        self,
        event_type: str,
        client_ip: str,
        details: str = "",
        user_id: Optional[str] = None,
        severity: str = "warning"
    ):
        """
        Logga eventi di sicurezza
        """
        try:
            security_log = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat(),
                "event_type": "security",
                "client_ip": client_ip,
                "endpoint": f"SECURITY:{event_type}",
                "user_id": user_id,
                "error_message": details,
                "additional_data": json.dumps({
                    "security_event": event_type,
                    "severity": severity
                }),
                "created_at": datetime.utcnow().isoformat(),
                "method": "log_security_event"
            }
            
            result = self.supabase.table("usage_logs").insert(security_log).execute()
            
            # Log anche nella console per eventi di sicurezza
            logger.warning(f"SECURITY: {event_type} - IP: {client_ip} - {details}")
            
        except Exception as e:
            logger.error(f"Errore nel logging dell'evento di sicurezza: {str(e)}")
    
    def _get_client_ip(self, request: Request) -> str:
        """
        Estrae l'IP del client considerando proxy e load balancer
        """
        logger.info('request _get_client_ip: ')
        logger.info(str(request))
        # Controlla gli header comuni per IP reali dietro proxy
        if request.headers:
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()
        
            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip
        
        return request.client.host if request.client else "unknown"

    # Cleanup Section
    async def cleanup_old_successful_log_api_call(self, days: int = 60) -> int:
        """Pulisce vecchi record di chiamate API completate"""
        try:
            cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
            
            # Prima ottieni i record da eliminare
            response = supabase_client.table('usage_logs')\
                .select('id')\
                .eq('status_code', '200')\
                .lt('created_at', cutoff_date)\
                .execute()
            
            if not response.data:
                return 0
            
            # Elimina i record
            ids_to_delete = [record['id'] for record in response.data]
            
            delete_response = supabase_client.table('usage_logs')\
                .delete()\
                .in_('id', ids_to_delete)\
                .execute()
            
            deleted_count = len(response.data)
            logger.info(f"Cleaned up {deleted_count} old usage logs")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up usage logs: {e}")
            return 0

# Crea un'istanza globale del logger
# api_logger = SupabaseAPILogger(supabase_client)

# Decorator per loggare automaticamente le chiamate API
def log_api_call(supabase_client: Client):
    def decorator(func):
        async def wrapper(request: Request = None, *args, **kwargs):
            start_time = datetime.utcnow()
            api_logger = SupabaseAPILogger(supabase_client)
            user_id = None
            error = None
            response = None
            
            try:
                # Estrai user_id dal token JWT se presente
                auth_header = request.headers.get("Authorization") if request else None
                if auth_header and auth_header.startswith("Bearer "):
                    try:
                        # Qui dovresti decodificare il JWT per ottenere l'user_id
                        # user_id = decode_jwt_and_get_user_id(auth_header.split(" ")[1])
                        pass
                    except:
                        pass
                
                # Esegui la funzione originale
                if request:
                    response = await func(request, *args, **kwargs)
                else:
                    response = await func(*args, **kwargs)
                
                return response
                
            except Exception as e:
                error = str(e)
                raise
            
            finally:
                if request:
                    # Calcola tempo di risposta
                    end_time = datetime.utcnow()
                    response_time = (end_time - start_time).total_seconds() * 1000
                    
                    # Logga la chiamata
                    await api_logger.log_api_call(
                        request=request,
                        response=response,
                        response_time=response_time,
                        user_id=user_id,
                        error=error
                    )
        
        return wrapper
    return decorator

# Funzioni di utilità per il logging manuale
async def log_request(
    supabase_client: Client,
    request: Request,
    response: Optional[Response] = None,
    response_time: Optional[float] = None,
    user_id: Optional[str] = None,
    error: Optional[str] = None
):
    """Funzione di utilità per logging manuale"""
    api_logger = SupabaseAPILogger(supabase_client)
    await api_logger.log_api_call(
        request=request,
        response=response,
        response_time=response_time,
        user_id=user_id,
        error=error
    )

async def log_security_event(
    supabase_client: Client,
    event: str,
    client_ip: str,
    details: str = "",
    user_id: Optional[str] = None
):
    """Funzione di utilità per logging eventi di sicurezza"""
    api_logger = SupabaseAPILogger(supabase_client)
    await api_logger.log_security_event(
        event_type=event,
        client_ip=client_ip,
        details=details,
        user_id=user_id
    )