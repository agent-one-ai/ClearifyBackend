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
    from jinja2 import Environment, FileSystemLoader, select_autoescape
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
        
        # Setup Jinja2 se disponibile
        if JINJA_AVAILABLE:
            template_dir = Path(__file__).parent.parent / "templates" / "emails"
            if template_dir.exists():
                self.jinja_env = Environment(
                    loader=FileSystemLoader(str(template_dir)),
                    autoescape=select_autoescape(['html', 'xml'])
                )
            else:
                self.jinja_env = None
                logger.warning(f"Email template directory not found: {template_dir}")
        else:
            self.jinja_env = None

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
                        'next_retry_at': datetime.now().isoformat()  # Per retry immediato
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

    def render_template(self, template_name: str, context: Dict) -> tuple[str, str]:
        """
        Renderizza template con priorità: Database > File > Hardcoded
        """
        try:
            # 1️⃣ PROVA PRIMA DAL DATABASE SUPABASE
            db_template = self._get_template_from_database(template_name)
            if db_template:
                logger.info(f"📄 Using database template: {template_name}")
                return self._render_database_template(db_template, context)
            
            # 2️⃣ PROVA DA FILE JINJA2
            # if JINJA_AVAILABLE and self.jinja_env:
            #     try:
            #         html_template = self.jinja_env.get_template(f"{template_name}.html")
            #         html_content = html_template.render(**context)
                    
            #         try:
            #             text_template = self.jinja_env.get_template(f"{template_name}.txt")
            #             text_content = text_template.render(**context)
            #         except Exception:
            #             text_content = None
                    
            #         logger.info(f"📁 Using file template: {template_name}")
            #         return html_content, text_content
                    
            #     except Exception as template_error:
            #         logger.warning(f"File template failed: {template_error}")
            
            # 3️⃣ FALLBACK: TEMPLATE HARDCODED
            # logger.info(f"🔧 Using hardcoded template: {template_name}")
            # return self._get_default_template(template_name, context)
                
        except Exception as e:
            logger.warning(f"Template system error: {str(e)}")
            return self._get_default_template(template_name, context)
    
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
                logger.info(f"Found database template: {template_name} v{template_data.get('version', '1.0')}")
                return template_data
            
            return None
            
        except Exception as e:
            logger.warning(f"Failed to fetch template from database: {str(e)}")
            return None
    
    def _render_database_template(self, template_data: Dict, context: Dict) -> tuple[str, str]:
        """Renderizza template dal database usando Jinja2"""
        try:
            if JINJA_AVAILABLE:
                from jinja2 import Template
                
                # HTML template  
                html_template = Template(template_data['html_template'])
                rendered_html = html_template.render(**context)
                
                # Text template (opzionale)
                rendered_text = None
                if template_data.get('text_template'):
                    text_template = Template(template_data['text_template'])
                    rendered_text = text_template.render(**context)
                
                return rendered_html, rendered_text
            else:
                # Se Jinja2 non è disponibile, usa template hardcoded
                logger.warning("Jinja2 not available for database template rendering")
                return self._get_default_template(template_data['name'], context)
            
        except Exception as e:
            logger.error(f"Failed to render database template: {str(e)}")
            return self._get_default_template(template_data['name'], context)

    def _get_default_template(self, template_name: str, context: Dict) -> tuple[str, str]:
        """Template di fallback hardcoded - SEMPRE funziona"""
        
        # Valori di default per evitare errori
        customer_name = context.get('customer_name', context.get('recipient_email', 'Cliente').split('@')[0])
        plan_type = context.get('plan_type', 'Premium').title()
        amount = context.get('amount', 0)
        payment_date = context.get('payment_date', datetime.now().strftime("%d/%m/%Y %H:%M"))
        payment_intent_id = context.get('payment_intent_id', 'N/A')
        
        if template_name == "payment_confirmation":
            # Converti amount da centesimi a euro se necessario
            amount_euro = amount / 100 if amount > 100 else amount
            
            html = f"""
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Conferma Pagamento - Clearify</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f3f4f6;">
    <div style="max-width: 600px; margin: 20px auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #2563eb, #1d4ed8); color: white; padding: 30px; text-align: center;">
            <h1 style="margin: 0; font-size: 28px;">🎉 Pagamento Confermato!</h1>
            <p style="margin: 10px 0 0 0; opacity: 0.9; font-size: 16px;">Grazie per aver scelto Clearify Premium</p>
        </div>
        
        <!-- Content -->
        <div style="padding: 30px;">
            <div style="text-align: center; font-size: 48px; margin: 20px 0;">✅</div>
            
            <p style="font-size: 16px; line-height: 1.6;">Ciao <strong>{customer_name}</strong>,</p>
            
            <p style="font-size: 16px; line-height: 1.6;">Il tuo pagamento è stato elaborato con successo! Il tuo abbonamento Clearify Premium è ora attivo.</p>
            
            <!-- Order Details -->
            <div style="background: #f0f9ff; padding: 20px; border-radius: 8px; margin: 25px 0; border-left: 4px solid #2563eb;">
                <h3 style="margin: 0 0 15px 0; color: #1e40af; font-size: 18px;">📋 Dettagli dell'ordine</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">Piano:</td>
                        <td style="padding: 8px 0;">{plan_type}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">Importo:</td>
                        <td style="padding: 8px 0; font-size: 20px; font-weight: bold; color: #059669;">€{amount_euro:.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">Data pagamento:</td>
                        <td style="padding: 8px 0;">{payment_date}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">ID Transazione:</td>
                        <td style="padding: 8px 0; font-family: monospace; font-size: 12px; color: #6b7280;">{payment_intent_id}</td>
                    </tr>
                </table>
            </div>
            
            <h3 style="color: #1f2937; margin: 25px 0 15px 0;">Cosa puoi fare ora:</h3>
            <ul style="font-size: 15px; line-height: 1.7;">
                <li>✨ <strong>Accesso completo</strong> a tutte le funzionalità premium</li>
                <li>🚀 <strong>Elaborazione testi illimitata</strong> con AI avanzata</li>
                <li>💬 <strong>Supporto prioritario</strong> dal nostro team</li>
                <li>📊 <strong>Analytics dettagliate</strong> sui tuoi progetti</li>
            </ul>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="https://clearify.com/dashboard" style="display: inline-block; background: #2563eb; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 16px;">
                    Inizia subito 🚀
                </a>
            </div>
            
            <div style="background: #fffbeb; border: 1px solid #fcd34d; padding: 15px; border-radius: 6px; margin: 20px 0;">
                <p style="margin: 0; font-size: 14px; color: #92400e;">
                    💡 <strong>Suggerimento:</strong> Salva questa email come conferma del tuo acquisto per future referenze.
                </p>
            </div>
            
            <p style="font-size: 14px; color: #6b7280; margin: 25px 0 0 0;">
                Se hai domande o problemi, il nostro team di supporto è sempre disponibile all'indirizzo 
                <a href="mailto:support@clearify.com" style="color: #2563eb;">support@clearify.com</a>
            </p>
        </div>
        
        <!-- Footer -->
        <div style="background: #f8fafc; padding: 20px; text-align: center; border-top: 1px solid #e5e7eb;">
            <p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Clearify</strong> - Il tuo assistente AI per l'elaborazione testi</p>
            <p style="margin: 5px 0 0 0; font-size: 12px; color: #9ca3af;">
                <a href="https://clearify.com" style="color: #6b7280; text-decoration: none;">clearify.com</a> | 
                <a href="mailto:support@clearify.com" style="color: #6b7280; text-decoration: none;">support@clearify.com</a>
            </p>
        </div>
    </div>
</body>
</html>
            """
            
            text = f"""
CONFERMA PAGAMENTO - CLEARIFY
============================

Ciao {customer_name},

Il tuo pagamento è stato elaborato con successo! 
Il tuo abbonamento Clearify Premium è ora attivo.

DETTAGLI DELL'ORDINE:
---------------------
🔹 Piano: {plan_type}
🔹 Importo: €{amount_euro:.2f}
🔹 Data: {payment_date}
🔹 ID Transazione: {payment_intent_id}

COSA PUOI FARE ORA:
-------------------
✨ Accesso completo a tutte le funzionalità premium
🚀 Elaborazione di testi illimitata con AI avanzata
💬 Supporto prioritario dal nostro team
📊 Analytics dettagliate sui tuoi progetti

Inizia subito: https://clearify.com/dashboard

Per domande: support@clearify.com

Grazie per aver scelto Clearify!
Il team di Clearify

---
Clearify - Il tuo assistente AI per l'elaborazione testi
https://clearify.com
            """
            
            return html, text
            
        elif template_name == "subscription_expiring":
            end_date = context.get('end_date', 'Presto')
            subscription_id = context.get('subscription_id', 'N/A')
            
            html = f"""
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>Rinnovo Abbonamento - Clearify</title>
</head>
<body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #f3f4f6;">
    <div style="max-width: 600px; margin: 20px auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        
        <div style="background: linear-gradient(135deg, #dc2626, #b91c1c); color: white; padding: 30px; text-align: center;">
            <h1 style="margin: 0; font-size: 24px;">⏰ Il tuo abbonamento sta scadendo</h1>
        </div>
        
        <div style="padding: 30px;">
            <div style="background: #fef2f2; border: 1px solid #fecaca; padding: 20px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0; font-weight: 500; color: #dc2626; font-size: 16px;">
                    Il tuo abbonamento <strong>{plan_type}</strong> scadrà il <strong>{end_date}</strong>
                </p>
            </div>
            
            <p style="font-size: 16px; line-height: 1.6;">Per continuare a utilizzare tutte le funzionalità premium di Clearify, rinnova il tuo abbonamento prima della scadenza.</p>
            
            <div style="text-align: center; margin: 30px 0;">
                <a href="https://clearify.com/checkout?renewal=true&sub_id={subscription_id}" 
                   style="display: inline-block; background: #dc2626; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: 600; font-size: 16px;">
                    Rinnova ora 🔄
                </a>
            </div>
        </div>
    </div>
</body>
</html>
            """
            
            text = f"""
IL TUO ABBONAMENTO STA SCADENDO
==============================

Il tuo abbonamento {plan_type} scadrà il {end_date}.

Per continuare a utilizzare Clearify Premium, rinnova ora:
https://clearify.com/checkout?renewal=true&sub_id={subscription_id}

Il team di Clearify
            """
            
            return html, text
            
        # Template di fallback generico
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Clearify</h2>
            <p>Grazie per aver utilizzato Clearify!</p>
            <p>Template: {template_name}</p>
        </body>
        </html>
        """
        text = f"Clearify - Template: {template_name}"
        
        return html, text

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
            
            html_body, text_body = self.render_template("subscription_expiring", context)
            
            return self.send_email_sync(
                to_email=to_email,
                subject="Il tuo abbonamento Clearify sta scadendo",
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
            logger.error(f"Error in send_subscription_expiring_email_service: {str(e)}")
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
            html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Problema Pagamento</title></head>
<body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f3f4f6;">
    <div style="max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; padding: 30px;">
        <h1 style="color: #dc2626; margin: 0 0 20px 0;">Problema con il pagamento</h1>
        
        <p>Ciao,</p>
        
        <p>Abbiamo riscontrato un problema durante l'elaborazione del tuo pagamento per l'abbonamento <strong>{plan_type}</strong>.</p>
        
        <div style="background: #fef2f2; padding: 15px; border-radius: 6px; margin: 20px 0;">
            <p style="margin: 0;"><strong>ID Transazione:</strong> {payment_intent_id}</p>
            {f'<p style="margin: 5px 0 0 0;"><strong>Errore:</strong> {error_message}</p>' if error_message else ''}
        </div>
        
        <p>Ti consigliamo di riprovare o di contattare il nostro supporto se il problema persiste.</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="https://clearify.com/checkout" 
               style="display: inline-block; background: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: 500;">
                Riprova Pagamento
            </a>
        </div>
        
        <p style="font-size: 14px; color: #6b7280;">
            Supporto: <a href="mailto:support@clearify.com">support@clearify.com</a>
        </p>
    </div>
</body>
</html>
            """
            
            return self.send_email_sync(
                to_email=to_email,
                subject="Problema con il tuo pagamento - Clearify",
                html_body=html_body,
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

# 🔥 FUNZIONI UTILITY AGGIORNATE con tracking Supabase
def send_payment_confirmation_email(
    to_email: str,
    plan_type: str,
    amount: float,
    payment_intent_id: str,
    customer_name: str = ""
) -> bool:
    """
    Funzione di utilità per inviare email di conferma pagamento con tracking Supabase
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
        
        # Renderizza template
        html_body, text_body = email_service.render_template("payment_confirmation", context)
        
        # 🔥 INVIA EMAIL con tracking completo
        success = email_service.send_email_sync(
            to_email=to_email,
            subject=f"✅ Conferma pagamento - Abbonamento {plan_type.title()}",
            html_body=html_body,
            text_body=text_body,
            email_type="payment_confirmation",  # 🔥 NUOVO
            payment_intent_id=payment_intent_id,  # 🔥 NUOVO
            metadata={  # 🔥 NUOVO
                'plan_type': plan_type,
                'amount_euros': amount / 100,
                'customer_name': customer_name
            }
        )
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Error in send_payment_confirmation_email: {str(e)}")
        return False

# 🔥 FUNZIONI HELPER PER GESTIRE EMAIL DATABASE
def get_failed_emails_for_retry(limit: int = 50) -> List[Dict]:
    """Recupera email fallite da ritentare"""
    try:
        result = supabase_client.table('email_queue')\
            .select('*')\
            .eq('status', 'failed')\
            .lte('retry_count', 3)\
            .order('created_at', desc=False)\
            .limit(limit)\
            .execute()
        
        return result.data or []
        
    except Exception as e:
        logger.error(f"Error fetching failed emails: {str(e)}")
        return []

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

def cleanup_old_emails(days: int = 30) -> int:
    """Pulisce email vecchie inviate con successo"""
    try:
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=days)
        
        result = supabase_client.table('email_queue')\
            .delete()\
            .eq('status', 'sent')\
            .lt('sent_at', cutoff_date.isoformat())\
            .execute()
        
        deleted_count = len(result.data) if result.data else 0
        logger.info(f"🗑️ Cleaned up {deleted_count} old emails")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error cleaning up emails: {str(e)}")
        return 0

# Istanza globale del servizio
email_service = EmailService()

# SCRIPT PER GESTIRE EMAIL FALLITE
def retry_failed_emails_from_database():
    """Script per ritentare email fallite salvate nel database"""
    try:
        failed_emails = get_failed_emails_for_retry(limit=10)
        
        if not failed_emails:
            logger.info("No failed emails to retry")
            return 0
        
        retry_count = 0
        success_count = 0
        
        for email_record in failed_emails:
            try:
                email_service = EmailService()
                
                # Riprova invio
                success = email_service.send_email_sync(
                    to_email=email_record['recipient_email'],
                    subject=email_record['subject'],
                    html_body=email_record['html_body'],
                    text_body=email_record.get('text_body'),
                    email_type=email_record['email_type'],
                    payment_intent_id=email_record.get('payment_intent_id'),
                    subscription_id=email_record.get('subscription_id'),
                    metadata=email_record.get('metadata', {})
                )
                
                if success:
                    success_count += 1
                    logger.info(f"Email retry successful: {email_record['recipient_email']}")
                else:
                    # Incrementa retry count
                    supabase_client.table('email_queue').update({
                        'retry_count': email_record['retry_count'] + 1,
                        'last_attempt_at': datetime.now().isoformat()
                    }).eq('id', email_record['id']).execute()
                
                retry_count += 1
                
            except Exception as e:
                logger.error(f"Error retrying email {email_record['id']}: {str(e)}")
        
        logger.info(f"Email retry completed: {success_count}/{retry_count} successful")
        return success_count
        
    except Exception as e:
        logger.error(f"Error in retry_failed_emails_from_database: {str(e)}")
        return 0