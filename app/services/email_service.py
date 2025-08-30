import smtplib
import ssl
import email.mime.text
import email.mime.multipart
import email.mime.base
import email.encoders
from typing import Dict, Optional, List
import logging
from datetime import datetime
import asyncio
import aiosmtplib
import os
from pathlib import Path
from app.core.supabase_client import supabase_client

# 🔥 FIX: Import specifici per evitare conflitti
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart  
from email.mime.base import MIMEBase
from email.encoders import encode_base64

# Jinja2 import con error handling
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape, Template
    JINJA_AVAILABLE = True
except ImportError:
    JINJA_AVAILABLE = False
    print("⚠️ Jinja2 not available - using fallback templates")

from app.core.config import Settings

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.settings = Settings()
        self.smtp_server = getattr(self.settings, 'EMAIL_HOST', 'smtp.gmail.com')
        self.smtp_port = getattr(self.settings, 'EMAIL_PORT', 587)
        self.sender_email = getattr(self.settings, 'EMAIL_HOST_USER', 'noreply@clearify.com')
        self.sender_password = getattr(self.settings, 'EMAIL_HOST_PASSWORD', '')
        self.use_tls = getattr(self.settings, 'EMAIL_USE_TLS', True)

    def send_email_sync(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachments: Optional[List[Dict]] = None,
        # 🔥 NUOVO: parametri per logging in database
        email_type: str = "system_notification",
        payment_intent_id: str = None,
        subscription_id: str = None,
        metadata: Dict = None
    ) -> bool:
        """
        Invia email sincrona e salva nel database
        """
        email_queue_id = None
        
        try:
            logger.info(f"📧 Sending email to {to_email}: {subject}")
            
            # Validazione input
            if not all([to_email, subject, html_body]):
                raise ValueError("Missing required email parameters")
            
            if not self.sender_email or not self.sender_password:
                raise ValueError("Email credentials not configured")

            # 🔥 SALVA EMAIL IN CODA DATABASE PRIMA DI INVIARE
            try:
                email_queue_data = {
                    'recipient_email': to_email,
                    'subject': subject,
                    'html_body': html_body,
                    'text_body': text_body,
                    'email_type': email_type,
                    'status': 'processing',
                    'payment_intent_id': payment_intent_id,
                    'subscription_id': subscription_id,
                    'metadata': metadata or {},
                    'created_at': datetime.now().isoformat()
                }
                
                result = supabase_client.table('email_queue').insert(email_queue_data).execute()
                
                if result.data:
                    email_queue_id = result.data[0]['id']
                    logger.info(f"📝 Email queued in database: {email_queue_id}")
                
            except Exception as db_error:
                logger.warning(f"Failed to save email to database: {str(db_error)}")

            # PREPARA E INVIA EMAIL
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = self.sender_email
            message["To"] = to_email
            message["Date"] = email.utils.formatdate(localtime=True)

            # Aggiungi corpo del messaggio
            if text_body:
                text_part = MIMEText(text_body, "plain", "utf-8")
                message.attach(text_part)
            
            html_part = MIMEText(html_body, "html", "utf-8")
            message.attach(html_part)

            # Aggiungi allegati se presenti
            if attachments:
                for attachment in attachments:
                    self._add_attachment(message, attachment)

            # 🔥 INVIA EMAIL
            start_time = datetime.now()
            context = ssl.create_default_context()
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.set_debuglevel(0)
                
                if self.use_tls:
                    server.starttls(context=context)
                    
                server.login(self.sender_email, self.sender_password)
                text = message.as_string()
                server.sendmail(self.sender_email, [to_email], text)

            processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            
            # 🔥 AGGIORNA STATUS COME INVIATA
            if email_queue_id:
                try:
                    supabase_client.table('email_queue').update({
                        'status': 'sent',
                        'sent_at': datetime.now().isoformat(),
                        'processing_time_ms': processing_time_ms
                    }).eq('id', email_queue_id).execute()
                    
                    logger.info(f"📧 Email status updated: sent")
                    
                except Exception as db_error:
                    logger.warning(f"Failed to update email status: {str(db_error)}")

            logger.info(f"✅ Email sent successfully to {to_email} in {processing_time_ms}ms")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send email to {to_email}: {str(e)}")
            
            # 🔥 AGGIORNA STATUS COME FALLITA
            if email_queue_id:
                try:
                    supabase_client.table('email_queue').update({
                        'status': 'failed',
                        'failed_at': datetime.now().isoformat(),
                        'error_message': str(e),
                        'retry_count': 0,
                        'next_retry_at': datetime.now().isoformat()
                    }).eq('id', email_queue_id).execute()
                    
                except Exception as db_error:
                    logger.warning(f"Failed to update error status: {str(db_error)}")
            
            return False
    
    async def send_email_async(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None
    ) -> bool:
        """
        Invia email asincrona
        """
        try:
            logger.info(f"📧 Sending async email to {to_email}: {subject}")
            
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = self.sender_email
            message["To"] = to_email
            message["Date"] = email.utils.formatdate(localtime=True)

            if text_body:
                text_part = MIMEText(text_body, "plain", "utf-8")
                message.attach(text_part)
            
            html_part = MIMEText(html_body, "html", "utf-8")
            message.attach(html_part)

            await aiosmtplib.send(
                message,
                hostname=self.smtp_server,
                port=self.smtp_port,
                username=self.sender_email,
                password=self.sender_password,
                use_tls=self.use_tls,
                timeout=30,
                start_tls=self.use_tls
            )

            logger.info(f"✅ Async email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to send async email to {to_email}: {str(e)}")
            return False

    def _add_attachment(self, message, attachment: Dict):
        """Aggiunge allegato al messaggio"""
        try:
            with open(attachment['path'], "rb") as attachment_file:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment_file.read())
            
            encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f"attachment; filename= {attachment['filename']}"
            )
            message.attach(part)
        except Exception as e:
            logger.warning(f"⚠️ Failed to add attachment {attachment['filename']}: {str(e)}")

    # 🔥 NUOVO METODO: Renderizza template e soggetto da database
    def render_template_and_subject(self, template_name: str, context: Dict) -> tuple[str, str, str]:
        """
        Renderizza template HTML, testo e soggetto dal database
        Returns: (rendered_subject, rendered_html, rendered_text)
        """
        try:
            # 1️⃣ RECUPERA TEMPLATE DAL DATABASE
            db_template = self._get_template_from_database(template_name)
            
            if not db_template:
                logger.error(f"❌ Template '{template_name}' not found in database")
                return self._get_fallback_template(template_name, context)
            
            logger.info(f"📄 Using database template: {template_name} v{db_template.get('version', '1.0')}")
            
            # 2️⃣ RENDERIZZA TUTTI I COMPONENTI
            return self._render_database_template_complete(db_template, context)
                
        except Exception as e:
            logger.error(f"❌ Template rendering error for '{template_name}': {str(e)}")
            return self._get_fallback_template(template_name, context)
    
    def _get_template_from_database(self, template_name: str) -> Optional[Dict]:
        """Recupera template dal database Supabase"""
        try:
            result = supabase_client.table('email_templates')\
                .select('*')\
                .eq('name', template_name)\
                .eq('is_active', True)\
                .order('version', desc=True)\
                .limit(1)\
                .execute()
            
            if result.data and len(result.data) > 0:
                template_data = result.data[0]
                logger.info(f"✅ Found database template: {template_name} v{template_data.get('version', '1.0')}")
                return template_data
            
            logger.warning(f"⚠️ Template '{template_name}' not found in database")
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch template '{template_name}' from database: {str(e)}")
            return None
    
    def _render_database_template_complete(self, template_data: Dict, context: Dict) -> tuple[str, str, str]:
        """Renderizza subject, HTML e text template dal database usando Jinja2"""
        try:
            if not JINJA_AVAILABLE:
                logger.warning("⚠️ Jinja2 not available - using fallback")
                return self._get_fallback_template(template_data['name'], context)
            
            # 🔥 RENDERIZZA SOGGETTO (sempre obbligatorio)
            if not template_data.get('subject_template'):
                raise ValueError(f"Missing subject_template for template: {template_data['name']}")
                
            subject_template = Template(template_data['subject_template'])
            rendered_subject = subject_template.render(**context)
            
            # 🔥 RENDERIZZA HTML (sempre obbligatorio)
            if not template_data.get('html_template'):
                raise ValueError(f"Missing html_template for template: {template_data['name']}")
                
            html_template = Template(template_data['html_template'])
            rendered_html = html_template.render(**context)
            
            # 🔥 RENDERIZZA TEXT (opzionale)
            rendered_text = None
            if template_data.get('text_template'):
                text_template = Template(template_data['text_template'])
                rendered_text = text_template.render(**context)
            
            logger.info(f"✅ Template rendered successfully: {template_data['name']}")
            return rendered_subject, rendered_html, rendered_text
            
        except Exception as e:
            logger.error(f"❌ Failed to render database template: {str(e)}")
            return self._get_fallback_template(template_data['name'], context)

    def _get_fallback_template(self, template_name: str, context: Dict) -> tuple[str, str, str]:
        """Template di fallback hardcoded quando il database non è disponibile"""
        
        if template_name == "payment_confirmation":
            subject = "✅ Pagamento confermato - Abbonamento {{plan_type}}"
            html_body = """
            <!DOCTYPE html>
            <html>
            <head><meta charset="UTF-8"><title>Pagamento Confermato</title></head>
            <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f3f4f6;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px;">
                    <h1 style="color: #059669; margin: 0 0 20px 0;">Pagamento Confermato!</h1>
                    <p>Ciao <strong>{{customer_name}}</strong>,</p>
                    <p>Il tuo pagamento per l'abbonamento <strong>{{plan_type}}</strong> è stato elaborato con successo.</p>
                    
                    <div style="background: #f0fdf4; padding: 20px; border-radius: 6px; margin: 20px 0;">
                        <p><strong>Piano:</strong> {{plan_type}}</p>
                        <p><strong>Importo:</strong> €{{amount}}</p>
                        <p><strong>Data:</strong> {{payment_date}}</p>
                        <p><strong>ID Transazione:</strong> {{payment_intent_id}}</p>
                    </div>
                    
                    <p style="font-size: 14px; color: #6b7280;">
                        Grazie per aver scelto Clearify!<br>
                        Supporto: <a href="mailto:support@clearify.com">support@clearify.com</a>
                    </p>
                </div>
            </body>
            </html>
            """
            text_body = """
Pagamento Confermato!

Ciao {{customer_name}},

Il tuo pagamento per l'abbonamento {{plan_type}} è stato elaborato con successo.

Dettagli:
- Piano: {{plan_type}}
- Importo: €{{amount}}
- Data: {{payment_date}}
- ID Transazione: {{payment_intent_id}}

Grazie per aver scelto Clearify!
Supporto: support@clearify.com
            """
            
        elif template_name == "subscription_expiring":
            subject = "⚠️ Il tuo abbonamento Clearify scade presto"
            html_body = """
            <!DOCTYPE html>
            <html>
            <head><meta charset="UTF-8"><title>Abbonamento in Scadenza</title></head>
            <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f3f4f6;">
                <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px;">
                    <h1 style="color: #d97706; margin: 0 0 20px 0;">Il tuo abbonamento sta scadendo</h1>
                    <p>Il tuo abbonamento <strong>{{plan_type}}</strong> scadrà il <strong>{{end_date}}</strong>.</p>
                    <p>Rinnova ora per continuare a usare tutte le funzionalità premium.</p>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="https://clearify.com/checkout" 
                           style="display: inline-block; background: #059669; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 500;">
                            Rinnova Abbonamento
                        </a>
                    </div>
                </div>
            </body>
            </html>
            """
            text_body = """
Il tuo abbonamento sta scadendo

Il tuo abbonamento {{plan_type}} scadrà il {{end_date}}.
Rinnova ora per continuare a usare tutte le funzionalità premium.

Rinnova su: https://clearify.com/checkout
            """
        
        else:
            # Template generico
            subject = "Notifica da Clearify"
            html_body = "<p>Template non trovato per: " + template_name + "</p>"
            text_body = "Template non trovato per: " + template_name
        
        # Renderizza con Jinja2 se disponibile, altrimenti simple replace
        if JINJA_AVAILABLE:
            try:
                subject_template = Template(subject)
                html_template = Template(html_body)
                text_template = Template(text_body) if text_body else None
                
                rendered_subject = subject_template.render(**context)
                rendered_html = html_template.render(**context)
                rendered_text = text_template.render(**context) if text_template else None
                
                return rendered_subject, rendered_html, rendered_text
            except:
                pass
        
        # Fallback senza Jinja2 - simple string replace
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            subject = subject.replace(placeholder, str(value))
            html_body = html_body.replace(placeholder, str(value))
            if text_body:
                text_body = text_body.replace(placeholder, str(value))
        
        return subject, html_body, text_body

    # 🔥 METODI AGGIORNATI CON NUOVO SISTEMA
    def send_subscription_expiring_email(
        self,
        to_email: str,
        plan_type: str,
        end_date: str,
        subscription_id: str
    ) -> bool:
        """
        Metodo del servizio per inviare email di scadenza abbonamento
        """
        try:
            context = {
                'plan_type': plan_type,
                'end_date': end_date,
                'subscription_id': subscription_id
            }
            
            # 🔥 USA NUOVO METODO CHE INCLUDE SUBJECT
            subject, html_body, text_body = self.render_template_and_subject("subscription_expiring", context)
            
            return self.send_email_sync(
                to_email=to_email,
                subject=subject,  # 🔥 SOGGETTO DAL DATABASE
                html_body=html_body,
                text_body=text_body,
                email_type="subscription_expiring",
                subscription_id=subscription_id,
                metadata={
                    'plan_type': plan_type,
                    'end_date': end_date
                }
            )
            
        except Exception as e:
            logger.error(f"Error in send_subscription_expiring_email: {str(e)}")
            return False

    def send_payment_failed_email_service(
        self,
        to_email: str,
        plan_type: str,
        payment_intent_id: str,
        error_message: str = ""
    ) -> bool:
        """
        Metodo del servizio per inviare email di pagamento fallito
        """
        try:
            context = {
                'plan_type': plan_type,
                'payment_intent_id': payment_intent_id,
                'error_message': error_message
            }
            
            # 🔥 USA TEMPLATE DA DATABASE
            subject, html_body, text_body = self.render_template_and_subject("payment_failed", context)
            
            return self.send_email_sync(
                to_email=to_email,
                subject=subject,  # 🔥 SOGGETTO DAL DATABASE
                html_body=html_body,
                text_body=text_body,
                email_type="payment_failed",
                payment_intent_id=payment_intent_id,
                metadata={
                    'plan_type': plan_type,
                    'error_message': error_message
                }
            )
            
        except Exception as e:
            logger.error(f"Error in send_payment_failed_email_service: {str(e)}")
            return False

# 🔥 FUNZIONI UTILITY AGGIORNATE con template da database
def send_payment_confirmation_email(
    to_email: str,
    plan_type: str,
    amount: float,
    payment_intent_id: str,
    customer_name: str = ""
) -> bool:
    """
    Funzione di utilità per inviare email di conferma pagamento con template da database
    """
    try:
        email_service = EmailService()
        
        # Context per template
        context = {
            'customer_name': customer_name or to_email.split('@')[0].title(),
            'plan_type': plan_type,
            'amount': amount,
            'payment_date': datetime.now().strftime("%d/%m/%Y alle %H:%M"),
            'payment_intent_id': payment_intent_id,
        }
        
        # 🔥 RENDERIZZA TEMPLATE E SOGGETTO DAL DATABASE
        subject, html_body, text_body = email_service.render_template_and_subject("payment_confirmation", context)
        
        # 🔥 INVIA EMAIL con tracking completo
        success = email_service.send_email_sync(
            to_email=to_email,
            subject=subject,  # 🔥 SOGGETTO DAL DATABASE
            html_body=html_body,
            text_body=text_body,
            email_type="payment_confirmation",
            payment_intent_id=payment_intent_id,
            metadata={
                'plan_type': plan_type,
                'amount_euros': amount / 100,
                'customer_name': customer_name
            }
        )
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Error in send_payment_confirmation_email: {str(e)}")
        return False

# 🔥 NUOVA FUNZIONE: Gestione template database
def create_or_update_email_template(
    name: str,
    subject_template: str,
    html_template: str,
    text_template: Optional[str] = None,
    version: str = "1.0",
    is_active: bool = True
) -> bool:
    """
    Crea o aggiorna un template email nel database
    """
    try:
        # Controlla se esiste già
        existing = supabase_client.table('email_templates')\
            .select('id')\
            .eq('name', name)\
            .eq('version', version)\
            .execute()
        
        template_data = {
            'name': name,
            'subject_template': subject_template,
            'html_template': html_template,
            'text_template': text_template,
            'version': version,
            'is_active': is_active,
            'updated_at': datetime.now().isoformat()
        }
        
        if existing.data:
            # Aggiorna esistente
            result = supabase_client.table('email_templates')\
                .update(template_data)\
                .eq('name', name)\
                .eq('version', version)\
                .execute()
            logger.info(f"✅ Updated email template: {name} v{version}")
        else:
            # Crea nuovo
            template_data['created_at'] = datetime.now().isoformat()
            result = supabase_client.table('email_templates')\
                .insert(template_data)\
                .execute()
            logger.info(f"✅ Created new email template: {name} v{version}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error creating/updating template '{name}': {str(e)}")
        return False

def get_email_statistics(days: int = 7) -> Dict:
    """Ottieni statistiche email degli ultimi N giorni"""
    try:
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=days)
        
        result = supabase_client.table('email_queue')\
            .select('status, email_type')\
            .gte('created_at', cutoff_date.isoformat())\
            .execute()
        
        data = result.data or []
        
        stats = {
            'total': len(data),
            'sent': len([e for e in data if e['status'] == 'sent']),
            'failed': len([e for e in data if e['status'] == 'failed']),
            'pending': len([e for e in data if e['status'] == 'pending']),
            'by_type': {}
        }
        
        # Statistiche per tipo
        for email in data:
            email_type = email['email_type']
            if email_type not in stats['by_type']:
                stats['by_type'][email_type] = {'sent': 0, 'failed': 0, 'pending': 0}
            stats['by_type'][email_type][email['status']] += 1
        
        # Calcola success rate
        if stats['total'] > 0:
            stats['success_rate'] = round((stats['sent'] / stats['total']) * 100, 2)
        else:
            stats['success_rate'] = 0
            
        return stats
        
    except Exception as e:
        logger.error(f"Error getting email statistics: {str(e)}")
        return {'total': 0, 'sent': 0, 'failed': 0, 'pending': 0, 'success_rate': 0}

# Istanza globale del servizio
email_service = EmailService()