from fastapi import APIRouter, HTTPException, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
import logging
import time
import uuid
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
    """Crea un nuovo ticket di supporto e invia email di conferma"""
    start_time = time.time()
    ticket_id = None
    
    try:
        logger.info(f"Creating support ticket for {ticket_request.email}")
        
        # Genera ID univoco per il ticket
        ticket_id = f"TK-{str(uuid.uuid4())[:8].upper()}"
        current_time = get_utc_now()
        
        # Prepara i dati per il database
        ticket_data = {
            'ticket_id': ticket_id,
            'name': ticket_request.name,
            'email': ticket_request.email,
            'category': ticket_request.category,
            'priority': ticket_request.priority,
            'subject': ticket_request.subject,
            'message': ticket_request.message,
            'attach_screenshot': ticket_request.attachScreenshot,
            'user_agent': ticket_request.userAgent,
            'user_id': ticket_request.userId,
            'user_info': ticket_request.userInfo.dict() if ticket_request.userInfo else None,
            'status': 'open',
            'created_at': current_time,
            'updated_at': current_time
        }
        
        # Salva nel database
        logger.info(f"Saving ticket {ticket_id} to database")
        result = supabase_client.table('support_tickets').insert(ticket_data).execute()
        
        if not result.data:
            raise Exception("Failed to create support ticket in database")
        
        logger.info(f"Ticket {ticket_id} saved successfully")
        
        # Prepara il contesto per l'email di conferma
        priority_colors = get_priority_colors(ticket_request.priority)
        expected_response = get_expected_response_time(ticket_request.priority)
        
        email_context = {
            'customer_name': ticket_request.name,
            'ticket_id': ticket_id,
            'subject': ticket_request.subject,
            'category': format_category(ticket_request.category),
            'priority': ticket_request.priority.title(),
            'priority_bg_color': priority_colors['bg'],
            'priority_text_color': priority_colors['text'],
            'submission_date': datetime.now().strftime("%B %d, %Y at %H:%M UTC"),
            'support_url': f"{settings.FRONTEND_URL}/support",
            'base_url': getattr(settings, 'BASE_URL', 'https://clearify.com')
        }
        
        # Invia email di conferma all'utente
        try:
            logger.info(f"Sending confirmation email to {ticket_request.email}")
            
            subject, html_body, text_body = email_service.render_template_and_subject(
                "support_received", 
                email_context
            )
            
            email_success = email_service.send_email_sync(
                to_email=ticket_request.email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                email_type="support_confirmation",
                metadata={
                    'ticket_id': ticket_id,
                    'category': ticket_request.category,
                    'priority': ticket_request.priority
                }
            )
            
            if email_success:
                logger.info(f"Confirmation email sent successfully to {ticket_request.email}")
            else:
                logger.warning(f"Failed to send confirmation email to {ticket_request.email}")
                
        except Exception as email_error:
            logger.error(f"Error sending confirmation email: {str(email_error)}")
            # Non far fallire il ticket per errore email
        
        # Invia notifica email interna al team di supporto
        try:
            logger.info("Sending internal notification to support team")
            
            internal_context = {
                'ticket_id': ticket_id,
                'customer_name': ticket_request.name,
                'customer_email': ticket_request.email,
                'subject': ticket_request.subject,
                'category': format_category(ticket_request.category),
                'priority': ticket_request.priority.title(),
                'message': ticket_request.message,
                'user_info': ticket_request.userInfo.dict() if ticket_request.userInfo else {},
                'user_agent': ticket_request.userAgent,
                'submission_date': datetime.now().strftime("%B %d, %Y at %H:%M UTC"),
                'admin_url': f"{settings.BASE_URL}/admin/tickets/{ticket_id}"
            }
            
            # Invia a email di supporto interna
            support_email = getattr(settings, 'SUPPORT_EMAIL', 'clearifysuppor@gmail.com')
            
            internal_subject, internal_html, internal_text = email_service.render_template_and_subject(
                "support_internal_notification",
                internal_context
            )
            
            email_service.send_email_sync(
                to_email=support_email,
                subject=internal_subject,
                html_body=internal_html,
                text_body=internal_text,
                email_type="support_internal",
                metadata={
                    'ticket_id': ticket_id,
                    'customer_email': ticket_request.email
                }
            )
            
        except Exception as internal_email_error:
            logger.error(f"Error sending internal notification: {str(internal_email_error)}")
            # Non far fallire il ticket per errore email interna
        
        logger.info(f"Support ticket {ticket_id} created successfully")
        
        return SupportTicketResponse(
            success=True,
            message="Support ticket created successfully",
            ticket_id=ticket_id,
            expected_response_time=expected_response
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating support ticket: {str(e)}")
        
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=ticket_request.userId if 'ticket_request' in locals() else None,
            error=str(e)
        )
        
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
        
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            error=str(e)
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve support ticket")

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
        
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            error=str(e)
        )
        
        raise HTTPException(status_code=500, detail="Failed to retrieve support tickets")