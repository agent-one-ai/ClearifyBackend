from celery import current_task
import asyncio
import logging
from datetime import datetime, timedelta, date, timezone
from typing import Dict, Any
from app.core.celery_app import celery_app
from app.services.openai_service import openai_service
from app.schemas.text_schemas import TextProcessingType
import uuid
import stripe
from app.core.config import Settings
from app.core.stripe_config import StripeConfig
from app.services.supabase_payment_service import payment_service
from app.core.supabase_client import supabase_client
from app.core.report_generator import ReportGenerator
import asyncio
# Import EmailService class invece delle funzioni
from app.services.email_service import EmailService
import logging
import os

# Setup logger per il sistema analytics
def setup_analytics_logger():
    logger = logging.getLogger('clearify_analytics')
    
    if logger.handlers:  # Evita duplicazione handlers
        return logger
        
    logger.setLevel(logging.INFO)
    
    # Formatter dettagliato
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(funcName)-20s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console sempre attivo
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    
    # File solo se specificato
    if Settings.LOG_TO_FILE.lower() == 'true': 
        file_handler = logging.FileHandler('analytics.log')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger

# Instanza il logger
#logger = setup_analytics_logger()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Crea istanza globale del servizio email
email_service = EmailService()

@celery_app.task(bind=True, name="process_text", acks_late=True)
def process_text_task(self, text: str, processing_type: str, user_id: str, options: dict = None):
    task_id = self.request.id
    try:
        # Log the text analyst 
        text_analyses_data = {
            'user_id': user_id,
            'session_id': task_id,
            'text_content': text,
            'text_length': len(str(text)),
            'text_word_count': len(text.split()),
            'status': 'processing',
            'created_at': datetime.now().isoformat(),
            'is_ai_generated': True,
            'confidence_score': 100
        }        
        result = supabase_client.table('text_analyses').insert(text_analyses_data).execute()
        
        logger.info(f"Starting text processing task {task_id} for user {user_id}")

        self.update_state(
            state="PROCESSING",
            meta={
                "status": "processing",
                "progress": 10,
                "message": "Processing started..."
            }
        )

        processing_type_enum = TextProcessingType(processing_type)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            processed_text = loop.run_until_complete(
                openai_service.process_text(
                    text=text,
                    processing_type=processing_type_enum,
                    options=options or {}
                )
            )
        finally:
            loop.close()

        original_word_count = len(text.split())
        processed_word_count = len(processed_text.split())

        # Update the text analyst
        processing_time_ms = ( datetime.utcnow() - datetime.fromisoformat(self.request.eta or datetime.utcnow().isoformat())
                            ) if self.request.eta else 0
        update_data_text_analyses = {
            'processed_text_word_count': processed_word_count,
            'processed_text': processed_text,
            'processed_text_lenght': len(str(processed_text)),
            'status': 'completed',
            'processing_time_ms': processing_time_ms,
            'processing_type': processing_type
        }
        supabase_client.table("text_analyses").update(update_data_text_analyses).eq("session_id", task_id).execute()
        
        result = {
            "status": "completed",
            "progress": 100,
            "result": {
                "original_text": text,
                "processed_text": processed_text,
                "processing_type": processing_type,
                "word_count_original": original_word_count,
                "word_count_processed": processed_word_count,
                "processing_time": processing_time_ms,
            },
            "message": "Text processing completed successfully"
        }

        logger.info(f"Task {task_id} completed successfully")
        return result

    except Exception as exc:
        update_data_text_analyses = {
            'status': 'failed',
            'error_text': f"Error: {str(exc)}"
        }
        supabase_client.table("text_analyses").update(update_data_text_analyses).eq("session_id", task_id).execute()
        
        logger.error(f"Task {task_id} failed: {str(exc)}")
        self.update_state(
            state="FAILURE",
            meta={
                "status": "failed",
                "progress": 0,
                "error": str(exc),
                "message": "Text processing failed"
            }
        )
        raise exc

@celery_app.task(name="cleanup_expired_tasks")
def cleanup_expired_tasks():
    try:
        logger.info("Cleanup task executed")
        return {"message": "Cleanup completed", "timestamp": datetime.utcnow().isoformat()}
    except Exception as exc:
        logger.error(f"Cleanup task failed: {str(exc)}")
        raise exc

@celery_app.task(name="health_check")
def health_check_task():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "message": "Worker is running"
    }

@celery_app.task(bind=True, name="create_payment_intent_task", acks_late=True)
def create_payment_intent_task(self, payment_data: Dict) -> Dict:
    """
    Task Celery per creare un Payment Intent Stripe con tracking Supabase
    """
    try:
        logger.info(f"Creating payment intent for {payment_data['customer_email']} - Task: {self.request.id}")
        
        if not _validate_payment_data(payment_data):
            raise ValueError("Invalid payment data")
        
        customer = _get_or_create_customer(
            email=payment_data['customer_email'],
            name=payment_data['customer_name'],
            billing_details=payment_data.get('billing_details', {}),
            metadata=payment_data.get('metadata', {})
        )
        
        payment_intent = stripe.PaymentIntent.create(
            amount=payment_data['amount'],
            currency=payment_data['currency'],
            customer=customer.id,
            automatic_payment_methods={'enabled': True},
            metadata={
                **payment_data.get('metadata', {}),
                'customer_email': payment_data['customer_email'],
                'plan_type': payment_data['plan_type'],
                'created_at': datetime.now().isoformat(),
                'celery_task_id': self.request.id,
            },
            receipt_email=payment_data['customer_email'],
            description=f"Clearify Premium - {payment_data['plan_type']} subscription"
        )
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                payment_service.create_payment_intent_record(
                    stripe_payment_intent_id=payment_intent.id,
                    stripe_customer_id=customer.id,
                    amount=payment_data['amount'],
                    currency=payment_data['currency'],
                    plan_type=payment_data['plan_type'],
                    customer_email=payment_data['customer_email'],
                    customer_name=payment_data['customer_name'],
                    billing_details=payment_data.get('billing_details'),
                    celery_task_id=self.request.id
                )
            )
        finally:
            loop.close()
        
        logger.info(f"Payment intent created: {payment_intent.id}")
        
        return {
            'success': True,
            'client_secret': payment_intent.client_secret,
            'customer_id': customer.id,
            'payment_intent_id': payment_intent.id,
            'task_id': self.request.id
        }
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        if e.http_status in [429, 500, 502, 503, 504]:
            raise self.retry(exc=e)
        raise e
        
    except Exception as e:
        logger.error(f"Error creating payment intent: {str(e)}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, name="process_payment_success_task", acks_late=True)
def process_payment_success_task(self, payment_data: Dict) -> Dict:
    """
    Task per processare il successo del pagamento.
    Email delegate a task separate per massima resilienza.
    """
    payment_intent_id = payment_data.get('payment_intent_id')
    customer_email = payment_data.get('customer_email')
    
    try:
        logger.info(f"Processing payment success for PI: {payment_intent_id} - Task: {self.request.id}")

        customer_name = payment_data.get('customer_name', '')
        customer_id = payment_data.get('customer_id')
        
        if payment_intent_id:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            if payment_intent.status != 'succeeded':
                logger.warning(f"Payment intent {payment_intent.id} status is {payment_intent.status}")
                raise ValueError(f"Payment not succeeded: {payment_intent.status}")
            
            if payment_intent.customer:
                customer = stripe.Customer.retrieve(payment_intent.customer)
                customer_name = customer.name or customer_name or customer_email.split('@')[0]
                customer_id = customer.id

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                payment_service.update_payment_intent_status(
                    stripe_payment_intent_id=payment_intent_id,
                    status='succeeded' if payment_intent_id else 'paid',
                    processing_status='completed',
                    completed_at=datetime.now()
                )
            )

            subscription_result = loop.run_until_complete(
                payment_service.create_or_update_subscription(
                    email=customer_email,
                    stripe_customer_id=customer_id,
                    stripe_payment_intent_id=payment_intent_id,
                    plan_type=payment_data.get('plan_type'),
                    status='active',
                    amount_paid=payment_data.get('amount', 0),
                    currency='EUR',
                    metadata={
                        'payment_method': 'stripe',
                        'processed_by_task': self.request.id,
                        'processed_at': datetime.now().isoformat()
                    }
                )
            )
        finally:
            loop.close()

        # DELEGA EMAIL A TASK SEPARATA
        email_task = send_confirmation_email_task.apply_async(
            kwargs={
                'email_data': {
                    'customer_email': customer_email,
                    'customer_name': customer_name,
                    'plan_type': payment_data.get('plan_type'),
                    'amount': payment_data.get('amount'),
                    'payment_intent_id': payment_intent_id or 'INVOICE',
                    'subscription_id': subscription_result.get('id'),
                    'payment_date': datetime.now().strftime("%d/%m/%Y alle %H:%M")
                }
            },
            queue="emails",
            priority=6,
            retry=True,
            retry_policy={
                'max_retries': 3,
                'interval_start': 60,
                'interval_step': 60,
                'interval_max': 300
            }
        )

        update_payment_analytics_task.apply_async(
            kwargs={
                'analytics_data': {
                    'date': datetime.now().date().isoformat(),
                    'success': True,
                    'amount': payment_data.get('amount', 0) / 100,
                    'plan_type': payment_data.get('plan_type'),
                    'customer_email': customer_email,
                    'payment_method': 'stripe',
                    'email_task_id': email_task.id
                }
            },
            queue="analytics",
            priority=1
        )

        logger.info(f"Payment processed successfully for {customer_email} - Email task: {email_task.id}")

        return {
            'success': True,
            'message': 'Payment processed successfully',
            'subscription_id': subscription_result.get('id'),
            'email_task_id': email_task.id
        }

    except Exception as e:
        logger.error(f"Error processing payment success: {str(e)}")

        if customer_email:
            send_payment_failed_notification_task.apply_async(
                kwargs={
                    'failure_data': {
                        'customer_email': customer_email,
                        'plan_type': payment_data.get('plan_type', ''),
                        'payment_intent_id': payment_intent_id,
                        'error_message': str(e),
                        'failed_at': datetime.now().isoformat()
                    }
                },
                queue="emails",
                priority=8
            )

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    payment_service.update_payment_intent_status(
                        stripe_payment_intent_id=payment_intent_id,
                        status='processing_failed',
                        processing_status='failed',
                        failed_at=datetime.now()
                    )
                )
            finally:
                loop.close()
        except Exception as db_error:
            logger.error(f"Failed to update payment status: {str(db_error)}")

        raise e

@celery_app.task(bind=True, name="send_confirmation_email_task", acks_late=True)
def send_confirmation_email_task(self, email_data: Dict):
    """
    Task DEDICATA per email di conferma pagamento usando EmailService direttamente
    """
    try:
        customer_email = email_data['customer_email']
        task_id = self.request.id
        
        logger.info(f"Starting confirmation email task {task_id} for {customer_email}")
        
        self.update_state(
            state="PROCESSING",
            meta={
                "status": "sending_email",
                "progress": 20,
                "message": "Preparing email content...",
                "recipient": customer_email
            }
        )

        required_fields = ['customer_email', 'plan_type', 'amount']
        for field in required_fields:
            if not email_data.get(field):
                raise ValueError(f"Missing required email field: {field}")

        self.update_state(
            state="PROCESSING", 
            meta={
                "status": "sending_email",
                "progress": 50,
                "message": "Sending email...",
                "recipient": customer_email
            }
        )

        # USA DIRETTAMENTE EmailService
        context = {
            'customer_name': email_data.get('customer_name', customer_email.split('@')[0]),
            'plan_type': email_data['plan_type'],
            'amount': email_data['amount'],
            'payment_date': email_data.get('payment_date', datetime.now().strftime("%d/%m/%Y alle %H:%M")),
            'payment_intent_id': email_data.get('payment_intent_id', 'N/A'),
        }
        
        subject, html_body, text_body = email_service.render_template_and_subject("payment_confirmation", context)
        
        email_success = email_service.send_email_sync(
            to_email=customer_email,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            email_type="payment_confirmation",
            payment_intent_id=email_data.get('payment_intent_id'),
            subscription_id=email_data.get('subscription_id'),
            metadata={
                'plan_type': email_data['plan_type'],
                'amount_euros': email_data['amount'] / 100,
                'customer_name': context['customer_name'],
                'celery_task_id': task_id
            }
        )
        
        if not email_success:
            raise ValueError("Email service returned failure status")

        self.update_state(
            state="SUCCESS",
            meta={
                "status": "completed",
                "progress": 100,
                "message": "Email sent successfully",
                "recipient": customer_email
            }
        )

        logger.info(f"Confirmation email sent successfully to {customer_email}")
        
        return {
            'success': True,
            'recipient': customer_email,
            'email_type': 'payment_confirmation',
            'sent_at': datetime.now().isoformat(),
            'task_id': task_id
        }
        
    except Exception as e:
        customer_email = email_data.get('customer_email', 'unknown')
        logger.error(f"Failed to send confirmation email to {customer_email}: {str(e)}")
        
        self.update_state(
            state="FAILURE",
            meta={
                "status": "failed",
                "progress": 0,
                "error": str(e),
                "message": "Email sending failed",
                "recipient": customer_email
            }
        )
        
        if self.request.retries < 3:
            retry_countdown = 60 * (2 ** self.request.retries)
            logger.info(f"Retrying email task in {retry_countdown} seconds (attempt {self.request.retries + 1}/3)")
            
            raise self.retry(
                exc=e,
                countdown=retry_countdown,
                max_retries=3
            )
        
        logger.critical(f"Email permanently failed for {customer_email} after 3 retries")
        
        return {
            'success': False,
            'error': str(e),
            'max_retries_reached': True,
            'recipient': customer_email,
            'requires_manual_intervention': True
        }

@celery_app.task(bind=True, name="send_payment_failed_notification_task", acks_late=True)
def send_payment_failed_notification_task(self, failure_data: Dict):
    """Task per notificare pagamenti falliti usando EmailService"""
    try:
        customer_email = failure_data.get('customer_email')
        if not customer_email:
            return {'success': False, 'error': 'No customer email provided'}
            
        logger.info(f"Sending payment failure notification to {customer_email}")
        
        # USA EmailService direttamente
        success = email_service.send_payment_failed_email_service(
            to_email=customer_email,
            plan_type=failure_data.get('plan_type', ''),
            payment_intent_id=failure_data.get('payment_intent_id', ''),
            error_message=failure_data.get('error_message', '')
        )
        
        return {
            'success': success,
            'recipient': customer_email,
            'sent_at': datetime.now().isoformat() if success else None
        }
        
    except Exception as e:
        logger.error(f"Error sending failure notification: {str(e)}")
        return {'success': False, 'error': str(e)}

@celery_app.task(bind=True, name="send_expiring_subscription_notification_task", acks_late=True)
def send_expiring_subscription_notification_task(self, notification_data: Dict):
    """Task per inviare notifiche di scadenza subscription usando EmailService"""
    try:
        customer_email = notification_data.get('customer_email')
        if not customer_email:
            return {'success': False, 'error': 'No customer email provided'}
            
        logger.info(f"Sending expiration notification to {customer_email}")
        
        # USA EmailService direttamente
        success = email_service.send_subscription_expiring_email_service(
            to_email=customer_email,
            plan_type=notification_data.get('plan_type', ''),
            end_date=notification_data.get('end_date', ''),
            subscription_id=notification_data.get('subscription_id', '')
        )
        
        return {
            'success': success,
            'recipient': customer_email,
            'sent_at': datetime.now().isoformat() if success else None
        }
        
    except Exception as e:
        logger.error(f"Error sending expiration notification: {str(e)}")
        return {'success': False, 'error': str(e)}

@celery_app.task(bind=True, name="handle_webhook_event_task", acks_late=True)
def handle_webhook_event_task(self, event_data: Dict):
    """Task per gestire eventi webhook - delega tutto a task separate"""
    try:
        event_type = event_data.get('type')
        logger.info(f"Processing webhook event: {event_type}")
        
        if event_type == 'payment_intent.succeeded':
            invoice_obj = event_data['data']['object']

            customer_email = invoice_obj.get('customer_email')
            if not customer_email and invoice_obj.get('customer'):
                customer = stripe.Customer.retrieve(invoice_obj['customer'])
                customer_email = customer.get('email')

            payment_intent_id = invoice_obj.get('payment_intent')
            amount_paid = invoice_obj.get('amount_paid', 0)
            metadata = invoice_obj.get('metadata', {})

            task_id = str(uuid.uuid4())
            process_payment_success_task.apply_async(
                kwargs={
                    'payment_data': {
                        'payment_intent_id': payment_intent_id,
                        'customer_id': invoice_obj.get('customer'),
                        'customer_email': customer_email,
                        'customer_name': metadata.get('customer_name', ''),
                        'plan_type': metadata.get('plan_type'),
                        'amount': amount_paid
                    }
                },
                task_id=task_id,
                queue="payments",
                priority=8
            )
            
            logger.info(f"Payment processing task queued: {task_id}")

        elif event_type == 'payment_intent.payment_failed':
            payment_intent = event_data['data']['object']
            logger.warning(f"Payment failed: {payment_intent.get('id')}")
            
            customer_email = payment_intent.get('customer_email')
            if not customer_email and payment_intent.get('customer'):
                customer = stripe.Customer.retrieve(payment_intent['customer'])
                customer_email = customer.get('email')
            
            if customer_email:
                send_payment_failed_notification_task.apply_async(
                    kwargs={
                        'failure_data': {
                            'customer_email': customer_email,
                            'plan_type': payment_intent.get('metadata', {}).get('plan_type', ''),
                            'payment_intent_id': payment_intent.get('id'),
                            'error_message': payment_intent.get('last_payment_error', {}).get('message', ''),
                            'failed_at': datetime.now().isoformat()
                        }
                    },
                    queue="emails",
                    priority=7
                )

        return {'success': True, 'processed': event_type}

    except Exception as e:
        logger.error(f"Error handling webhook event: {str(e)}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, name="update_payment_analytics_task", acks_late=True)
def update_payment_analytics_task(self, analytics_data: Dict):
    """Task per aggiornare analytics giornaliere con metriche email"""
    try:
        date = analytics_data['date']
        
        existing = supabase_client.table('payment_analytics')\
            .select('*')\
            .eq('date', date)\
            .execute()
        
        if existing.data:
            current = existing.data[0]
            updated_data = {
                'total_payments': current['total_payments'] + 1,
                'successful_payments': current['successful_payments'] + (1 if analytics_data['success'] else 0),
                'failed_payments': current['failed_payments'] + (0 if analytics_data['success'] else 1),
                'total_revenue': float(current['total_revenue']) + (analytics_data['amount'] if analytics_data['success'] else 0)
            }
            
            if 'email_task_id' in analytics_data:
                updated_data['emails_sent'] = current.get('emails_sent', 0) + 1
            
            if analytics_data['success']:
                if analytics_data['plan_type'] == 'monthly':
                    updated_data['revenue_monthly_plans'] = float(current['revenue_monthly_plans']) + analytics_data['amount']
                else:
                    updated_data['revenue_yearly_plans'] = float(current['revenue_yearly_plans']) + analytics_data['amount']
            
            supabase_client.table('payment_analytics')\
                .update(updated_data)\
                .eq('date', date)\
                .execute()
        else:
            new_data = {
                'date': date,
                'total_payments': 1,
                'successful_payments': 1 if analytics_data['success'] else 0,
                'failed_payments': 0 if analytics_data['success'] else 1,
                'total_revenue': analytics_data['amount'] if analytics_data['success'] else 0,
                'revenue_monthly_plans': analytics_data['amount'] if (analytics_data['success'] and analytics_data['plan_type'] == 'monthly') else 0,
                'revenue_yearly_plans': analytics_data['amount'] if (analytics_data['success'] and analytics_data['plan_type'] == 'yearly') else 0,
                'emails_sent': 1 if 'email_task_id' in analytics_data else 0,
                'emails_failed': 0
            }
        
            supabase_client.table('payment_analytics')\
                .insert(new_data)\
                .execute()

        logger.info(f"Analytics updated for {date}")
        return {'success': True}
        
    except Exception as e:
        logger.error(f"Error updating analytics: {str(e)}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, name="send_verification_email_task", acks_late=True)
def send_verification_email_task(self, email_data: Dict):
    """
    Task per inviare email di verifica indirizzo
    """
    try:
        to_email = email_data['to_email']
        task_id = self.request.id
        
        logger.info(f"Starting verification email task {task_id} for {to_email}")
        
        self.update_state(
            state="PROCESSING",
            meta={
                "status": "sending_email",
                "progress": 20,
                "message": "Preparing email content...",
                "recipient": to_email
            }
        )

        logger.info(f"================TOKEN======================")
        logger.info(f"Token value {email_data['verificationToken']}")

        required_fields = ['to_email', 'username', 'verificationToken']
        for field in required_fields:
            if not email_data.get(field):
                raise ValueError(f"Missing required email field: {field}")

        self.update_state(
            state="PROCESSING", 
            meta={
                "status": "sending_email",
                "progress": 50,
                "message": "Sending email...",
                "recipient": to_email
            }
        )

        email_success = email_service.send_verification_email(email_data['to_email'], email_data['username'], email_data['verificationToken'])
        
        if not email_success:
            raise ValueError("Email service returned failure status")

        self.update_state(
            state="SUCCESS",
            meta={
                "status": "completed",
                "progress": 100,
                "message": "Email sent successfully",
                "recipient": to_email
            }
        )

        logger.info(f"Confirmation email sent successfully to {to_email}")
        
        return {
            'success': True,
            'recipient': to_email,
            'email_type': 'payment_confirmation',
            'sent_at': datetime.now().isoformat(),
            'task_id': task_id
        }
        
    except Exception as e:
        to_email = email_data.get('to_email', 'unknown')
        logger.error(f"Failed to send confirmation email to {to_email}: {str(e)}")
        
        self.update_state(
            state="FAILURE",
            meta={
                "status": "failed",
                "progress": 0,
                "error": str(e),
                "message": "Email sending failed",
                "recipient": to_email
            }
        )
        
        if self.request.retries < 3:
            retry_countdown = 60 * (2 ** self.request.retries)
            logger.info(f"Retrying email task in {retry_countdown} seconds (attempt {self.request.retries + 1}/3)")
            
            raise self.retry(
                exc=e,
                countdown=retry_countdown,
                max_retries=3
            )
        
        logger.critical(f"Email permanently failed for {to_email} after 3 retries")
        
        return {
            'success': False,
            'error': str(e),
            'max_retries_reached': True,
            'recipient': to_email,
            'requires_manual_intervention': True
        }

@celery_app.task(bind=True, name="check_expiring_subscriptions_task", acks_late=True)
def check_expiring_subscriptions_task(self):
    """Task per controllare subscription in scadenza"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            expiring = loop.run_until_complete(
                payment_service.get_expiring_subscriptions(days_ahead=7)
            )
        finally:
            loop.close()
        
        for subscription in expiring:
            send_expiring_subscription_notification_task.delay({
                'customer_email': subscription['email'],
                'plan_type': subscription['plan_type'],
                'end_date': subscription['end_date'],
                'subscription_id': subscription['id']
            })
        
        logger.info(f"Found {len(expiring)} expiring subscriptions")
        return {'expiring_count': len(expiring)}
        
    except Exception as e:
        logger.error(f"Error checking expiring subscriptions: {str(e)}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, name="cleanup_old_payment_intents_task", acks_late=True)
def cleanup_old_payment_intents_task(self):
    """Task periodico per pulire vecchi payment intent"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            deleted_count = loop.run_until_complete(
                payment_service.cleanup_old_payment_intents(days=7)
            )
            logger.info(f"Cleaned up {deleted_count} old payment intents")
            return {'deleted_count': deleted_count}
        finally:
            loop.close()             
    except Exception as e:
        logger.error(f"Error in cleanup task: {str(e)}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, name="payment_health_check_task", acks_late=True)
def payment_health_check_task(self):
    """Task per controllare la salute del sistema di pagamenti"""
    try:
        stripe.Account.retrieve()
        
        test_response = supabase_client.table('user_subscriptions')\
            .select('count')\
            .limit(1)\
            .execute()
        
        yesterday = datetime.now() - timedelta(days=1)
        
        analytics_result = supabase_client.table('payment_analytics')\
            .select('*')\
            .eq('date', yesterday.date().isoformat())\
            .execute()
        
        analytics = analytics_result.data[0] if analytics_result.data else {}
        
        health_status = {
            'stripe_connection': True,
            'supabase_connection': True,
            'last_24h_payments': analytics.get('total_payments', 0),
            'last_24h_revenue': float(analytics.get('total_revenue', 0)),
            'last_24h_emails': analytics.get('emails_sent', 0),
            'timestamp': datetime.now().isoformat()
        }
        
        logger.info(f"Payment system health check completed: {health_status}")
        return health_status
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            'stripe_connection': False,
            'supabase_connection': False,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }

# Analicys section  
@celery_app.task(bind=True, name="send_daily_report_task", acks_late=True)
def send_daily_report_task(self):
    """
    Task DEDICATA per email report giornaliero usando EmailService direttamente
    """
    print("="*50)
    print("TASK SEND_DAILY_REPORT_TASK CHIAMATO!")
    print(f"Task ID: {self.request.id}")
    print(f"Timestamp: {datetime.now()}")
    print("="*50)
    try:
        logger.info(f"🚀 TASK STARTED!")
        generator = ReportGenerator()

        logger.info(f"Starting generation of the report")
        yesterday = date.today() - timedelta(days=1)
        result = asyncio.run(
            generator.generate_daily_report(target_date=yesterday, send_email=True)
        )

        return {
            'success': result,
            'email_type': 'analytics',
            'sent_at': datetime.now().isoformat(),
        }
        
    except Exception as e:
        print(f"🚀 TASK FAILED: {str(e)}!")
        logger.error(f"Failed to send report email task:  {str(e)}")
            
        return {
            'success': False,
            'error': str(e),
            'max_retries_reached': True,
            'requires_manual_intervention': True
        }

# Payment section
@celery_app.task(bind=True, name="process_expiring_subscriptions", acks_late=True)
def process_expiring_subscriptions(self):
    """
    Task che informa l'utente che il proprio abbonamento è in scandenza
    """
    print("="*50)
    print("TASK process_expiring_subscriptions CHIAMATO!")
    print(f"Task ID: {self.request.id}")
    print(f"Timestamp: {datetime.now()}")
    print("="*50)
    try:
        logger.info(f"🚀 TASK STARTED!")

        # Salvo le variabili
        seven_days_from_now = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        now = datetime.now(timezone.utc).isoformat()

        # Cerco tutte le fatture che:
        # - non sono scadute
        # - non è stata ancora inviata la mail
        # - mancano al massimo 7 giorni alla scadenza
        result = supabase_client.table("user_subscriptions") \
            .select("users(full_name), plan_type, end_date, email, id") \
            .eq("status", "active") \
            .eq("expiring_mail_sent", False) \
            .gte("end_date", now) \
            .lte("end_date", seven_days_from_now) \
            .order("end_date", desc=True) \
            .limit(100)\
            .execute()

        # Creo la lista degli abbonamenti in scadenza e una lista di oggetti
        users_seen = set()
        expiring_subscriptions = []

        # Ciclo su tutti gli abbonamenti trovati
        for record in result.data:
            email = record['email']
            
            # Salto se ho già elaborato questo utente
            if email in users_seen:
                continue
            
            # Aggiungo l'utente
            users_seen.add(email)
            
            # Recupero tutte le variabili necessarie e le aggiungo alla lista
            completed_date = datetime.fromisoformat(record['end_date'].replace('Z', '+00:00'))
            days_remaining = (completed_date - datetime.now(timezone.utc)).days
            record['days_remaining'] = days_remaining
            record['full_name'] = record['users']['full_name']
            expiring_subscriptions.append(record)

        # Ciclo su tutti gli abbonamenti in scadenza
        for subscription in expiring_subscriptions:
            context = {                
                'user_name': subscription['full_name'],
                'plan_type': subscription['plan_type'],
                'expiration_date': datetime.fromisoformat(subscription['end_date'].replace('Z', '+00:00')).strftime("%d %b %Y"),
                'days_remaining': record['days_remaining'],
            }

            # Recupero il template e invio la mail
            subject, html_body, text_body = email_service.render_template_and_subject("subscription_expiring", context)
            email_success = email_service.send_email_sync(
                to_email=subscription['email'],
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                email_type="subscription_expiring",
                metadata={
                    'user_name': context['user_name'],
                    'plan_type': context['plan_type'],
                    'expiration_date': str(context['expiration_date']),
                    'days_remaining': context['days_remaining']
                }
            )

            # Se la mail è stata inviata con successo, aggiorno il campo per evitare di inviarla di nuovo nel prossimo ciclo
            if email_success:
                supabase_client.table("user_subscriptions") \
                            .update({"expiring_mail_sent": True}) \
                            .eq("id", subscription['id']) \
                            .execute()

        return {
            'success': True,
            'email_type': 'subscription_expiring',
            'sent_at': datetime.now().isoformat(),
        }
        
    except Exception as e:
        logger.error(f"Failed to process expiring subscriptions task:  {str(e)}")
            
        return {
            'success': False,
            'error': str(e),
            'max_retries_reached': True,
            'requires_manual_intervention': True
        }
    
@celery_app.task(bind=True, name="process_expired_subscriptions", acks_late=True)
def process_expired_subscriptions(self):
    """
    Task che informa l'utente che il proprio abbonamento è scaduto e aggiorna l'anagrafica
    """
    print("="*50)
    print("TASK process_expired_subscriptions CHIAMATO!")
    print(f"Task ID: {self.request.id}")
    print(f"Timestamp: {datetime.now()}")
    print("="*50)
    try:
        logger.info(f"🚀 TASK STARTED!")

        # Salvo le variabili
        now = datetime.now(timezone.utc).isoformat()

        # Cerco tutti gli abbonamenti che:
        # - sono scaduti 
        # - sono ancora attivi
        # - non è stata ancora inviata la mail
        result = supabase_client.table("user_subscriptions") \
            .select("users(full_name), plan_type, end_date, email, id") \
            .eq("status", "active") \
            .eq("expired_mail_sent", False) \
            .lt("end_date", now) \
            .order("end_date", desc=True) \
            .limit(100)\
            .execute()
        
        # Creo la lista degli abbonamenti scaduti e una lista di oggetti
        users_seen = set()
        expired_subscriptions = []
        
        # Ciclo su tutti gli abbonamenti trovati
        for record in result.data:
            email = record['email']
            
            # Salto se ho già elaborato questo utente
            if email in users_seen:
                continue
            
            # Aggiungo l'utente
            users_seen.add(email)
            
            # Recupero tutte le variabili necessarie e le aggiungo alla lista
            record['full_name'] = record['users']['full_name']
            expired_subscriptions.append(record)
        
        # Ciclo su tutti gli abbonamenti scaduti
        for subscription in expired_subscriptions:
            context = {                
                'user_name': subscription['full_name'],
                'plan_type': subscription['plan_type'],
                'expiration_date': datetime.fromisoformat(subscription['end_date'].replace('Z', '+00:00')).strftime("%d %b %Y"),
            }

            # Recupero il template e invio la mail
            subject, html_body, text_body = email_service.render_template_and_subject("subscription_expired", context)
            email_success = email_service.send_email_sync(
                to_email=subscription['email'],
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                email_type="subscription_expired",
                metadata={
                    'user_name': context['user_name'],
                    'plan_type': context['plan_type'],
                    'expiration_date': str(context['expiration_date'])
                }
            )

            # Se la mail è stata inviata con successo, aggiorno il campo per evitare di inviarla di nuovo nel prossimo ciclo
            if email_success:
                # Aggiorno lo stato del abbonamento del utente
                supabase_client.table("user_subscriptions") \
                            .update({"expired_mail_sent": True,
                                     'status': 'canceled',
                                     'canceled_at': datetime.now().isoformat()}) \
                            .eq("id", subscription['id']) \
                            .execute()
                
                # Aggiorno anche l'anagrafica del utente
                supabase_client.table("users") \
                        .update({"subscription_tier": 'free'}) \
                        .eq("email", subscription['email']) \
                        .execute()

        return {
            'success': True,
            'email_type': 'subscription_expired',
            'sent_at': datetime.now().isoformat(),
        }
        
    except Exception as e:
        logger.error(f"Failed to process expired subscriptions task:  {str(e)}")
            
        return {
            'success': False,
            'error': str(e),
            'max_retries_reached': True,
            'requires_manual_intervention': True
        }


# Utility functions
def _validate_payment_data(data: Dict) -> bool:
    """Valida i dati del pagamento"""
    required_fields = ['amount', 'currency', 'customer_email', 'customer_name', 'plan_type']
    
    for field in required_fields:
        if field not in data or not data[field]:
            logger.error(f"Missing required field: {field}")
            return False
    
    if data['amount'] < StripeConfig.MIN_AMOUNT:
        logger.error(f"Amount too low: {data['amount']}")
        return False
    
    if not StripeConfig.is_valid_plan(data['plan_type']):
        logger.error(f"Invalid plan type: {data['plan_type']}")
        return False
    
    return True

def _get_or_create_customer(email: str, name: str, billing_details: Dict, metadata: Dict):
    """Cerca o crea un customer Stripe"""
    try:
        existing_customers = stripe.Customer.list(email=email, limit=1)
        
        if existing_customers.data:
            customer = existing_customers.data[0]
            logger.info(f"Found existing customer: {customer.id}")
            return customer
        
        customer = stripe.Customer.create(
            email=email,
            name=name,
            address=billing_details.get('address'),
            metadata={
                'source': 'clearify_checkout',
                **metadata
            }
        )
        
        logger.info(f"Created new customer: {customer.id}")
        return customer
        
    except Exception as e:
        logger.error(f"Error managing customer: {str(e)}")
        raise e