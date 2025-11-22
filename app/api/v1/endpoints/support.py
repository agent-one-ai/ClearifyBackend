from fastapi import APIRouter, HTTPException, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
import logging
import time
import uuid
import httpx
from datetime import datetime, timezone

from app.core.config import settings
from app.core.supabase_client import supabase_client
from app.schemas.frontend import Tone, ContentTemplate
from app.schemas.support import UserInfo, SupportTicketRequest, SupportTicketResponse
from app.core.logging import SupabaseAPILogger
from app.services.email_service import email_service

router = APIRouter()
security = HTTPBearer()
api_logger = SupabaseAPILogger(supabase_client)

# Configurazione logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

from typing import List

# ================================
# UTILITY FUNCTIONS
# ================================

def get_priority_colors(priority: str) -> Dict[str, str]:
    """Restituisce i colori per la priorità"""
    priority_colors = {
        'urgent': {'bg': '#fecaca', 'text': '#dc2626'},
        'high': {'bg': '#fed7aa', 'text': '#ea580c'},
        'medium': {'bg': '#fef3c7', 'text': '#d97706'},
        'low': {'bg': '#f3f4f6', 'text': '#6b7280'}
    }
    return priority_colors.get(priority, priority_colors['medium'])

def get_expected_response_time(priority: str) -> str:
    """Restituisce il tempo di risposta atteso"""
    response_times = {
        'urgent': 'Within 2-4 hours',
        'high': 'Within 4-8 hours', 
        'medium': 'Within 1-2 business days',
        'low': 'Within 2-3 business days'
    }
    return response_times.get(priority, response_times['medium'])

def format_category(category: str) -> str:
    """Formatta il nome della categoria per display"""
    category_names = {
        'general': 'General Support',
        'technical': 'Technical Issue',
        'billing': 'Billing & Payment',
        'feature': 'Feature Request'
    }
    return category_names.get(category, category.title())

def get_utc_now() -> str:
    """Restituisce timestamp UTC formattato"""
    return datetime.now(timezone.utc).isoformat()
    
# ================================
# SUPPORT TICKET ENDPOINTS
# ================================

@router.post("/ticket", response_model=SupportTicketResponse)
async def create_support_ticket(
    ticket_request: SupportTicketRequest,
    request: Request
):
    """Chiamo automazione n8n per l'integrazione su Linear"""
    start_time = time.time()
    ticket_id = None
    
    try:
        logger.info(f"Creating support ticket for {ticket_request.customer_email}")
        
        # Genera ID univoco per il ticket
        ticket_id = f"TK-{str(uuid.uuid4())[:8].upper()}"
        current_time = get_utc_now()
        
        # Prepara i dati per il database
        ticket_data = {
            'action': ticket_request.action,
            'team': ticket_request.team,
            'customer_email': ticket_request.customer_email,
            'category': ticket_request.category,
            'priority': ticket_request.priority,
            'title': ticket_request.title,
            'description': ticket_request.description,
            'original_message': ticket_request.original_message,
            'needScreenshots': ticket_request.needScreenshots,
            'labels': ticket_request.labels
        }
        
        # Salva nel database
        #logger.info(f"Saving ticket {ticket_id} to database")
        #result = supabase_client.table('support_tickets').insert(ticket_data).execute()
        
        #if not result.data:
        #    raise Exception("Failed to create support ticket in database")
        
        #logger.info(f"Ticket {ticket_id} saved successfully")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://agentonesrl.app.n8n.cloud/webhook/issue",
                json=ticket_data,
                timeout=10.0
            )
        
        if response.status_code >= 400:
            logger.warning(f"n8n responded with {response.status_code}: {response.text}")
        else:
            logger.info("Successfully sent ticket to n8n webhook")

        # Prepara il contesto per l'email di conferma
        priority_colors = get_priority_colors(ticket_request.priority)
        expected_response = get_expected_response_time(ticket_request.priority)
        
        #email_context = {
        #    'customer_name': ticket_request.name,
        #    'ticket_id': ticket_id,
        #    'subject': ticket_request.subject,
        #    'category': format_category(ticket_request.category),
        #    'priority': ticket_request.priority.title(),
        #    'priority_bg_color': priority_colors['bg'],
        #    'priority_text_color': priority_colors['text'],
        #    'submission_date': datetime.now().strftime("%B %d, %Y at %H:%M UTC"),
        #    'support_url': f"{settings.FRONTEND_URL}/support",
        #    'base_url': getattr(settings, 'BASE_URL', 'https://clearify.com')
        #}
        
        # Invia email di conferma all'utente
        #try:
        #    logger.info(f"Sending confirmation email to {ticket_request.email}")
        #    
        #    subject, html_body, text_body = email_service.render_template_and_subject(
        #        "support_received", 
        #        email_context
        #    )
            
        #    email_success = email_service.send_email_sync(
        #        to_email=ticket_request.email,
        #        subject=subject,
        #        html_body=html_body,
        #        text_body=text_body,
        #        email_type="support_confirmation",
        #        metadata={
        #            'ticket_id': ticket_id,
        #            'category': ticket_request.category,
        #            'priority': ticket_request.priority
        #        }
        #    )
            
        #    if email_success:
        #        logger.info(f"Confirmation email sent successfully to {ticket_request.email}")
        #    else:
        #        logger.warning(f"Failed to send confirmation email to {ticket_request.email}")
                
        #except Exception as email_error:
        #    logger.error(f"Error sending confirmation email: {str(email_error)}")
        #    # Non far fallire il ticket per errore email
        
        
        return SupportTicketResponse(
            success=response.json().get("success"),
            message=response.json().get("message"),
            value=response.json().get("value")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating support ticket: {str(e)}")
        
        raise HTTPException(
            status_code=500, 
            detail="Failed to create support ticket. Please try again later."
        )

@router.get("/ticket/{ticket_id}")
async def get_support_ticket(
    ticket_id: str,
    request: Request
):
    """Recupera un ticket di supporto specifico"""
    start_time = time.time()
    
    try:
        logger.info(f"Retrieving support ticket: {ticket_id}")
        
        result = supabase_client.table('support_tickets')\
            .select('*')\
            .eq('ticket_id', ticket_id)\
            .execute()
        
        if not result.data:
            raise HTTPException(
                status_code=404, 
                detail=f"Support ticket {ticket_id} not found"
            )
        
        ticket_data = result.data[0]
        
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response=request, # Muaad da guardare: tanto mi salvo solo lo status code su DB 
            response_time=process_time,
            additional_data={
                "action": "get_support_ticket",
                "ticket_id": ticket_id
            }
        )
        
        return ticket_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving support ticket {ticket_id}: {str(e)}")
        error = HTTPException(status_code=500, detail="Failed to retrieve support ticket")
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response=error,
            response_time=process_time,
            error=str(e)
        )
        
        return error

@router.get("/tickets")
async def list_support_tickets(
    request: Request,
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """Lista i ticket di supporto con filtri opzionali"""
    start_time = time.time()
    
    try:
        logger.info("Listing support tickets")
        
        query = supabase_client.table('support_tickets')\
            .select('*')\
            .order('created_at', desc=True)\
            .range(offset, offset + limit - 1)
        
        if status:
            query = query.eq('status', status)
        if category:
            query = query.eq('category', category)
        if priority:
            query = query.eq('priority', priority)
            
        result = query.execute()
        tickets_data = result.data or []
        
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            response=request, # Muaad da guardare: tanto mi salvo solo lo status code su DB
            additional_data={
                "action": "list_support_tickets",
                "count": len(tickets_data),
                "filters": {
                    "status": status,
                    "category": category,
                    "priority": priority
                }
            }
        )
        
        return {
            "tickets": tickets_data,
            "count": len(tickets_data),
            "offset": offset,
            "limit": limit
        }
        
    except Exception as e:
        logger.error(f"Error listing support tickets: {str(e)}")
        error = HTTPException(status_code=500, detail="Failed to retrieve support tickets")
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response=error,
            response_time=process_time,
            error=str(e)
        )
        
        return error
        