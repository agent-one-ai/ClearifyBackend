from celery import current_task
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any

from app.core.celery_app import celery_app
from app.services.openai_service import openai_service
from app.schemas.text_schemas import TextProcessingType
import uuid
import stripe
from app.core.config import Settings
from app.core.stripe_config import StripeConfig
from app.services.supabase_payment_service import payment_service
#from app.services.email_service import send_payment_confirmation_email

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, name="process_text", acks_late=True)
def process_text_task(self, text: str, processing_type: str, user_id: str, options: dict = None):
    task_id = self.request.id
    try:
        logger.info(f"Starting text processing task {task_id} for user {user_id}")

        # Aggiorno lo stato del task
        self.update_state(
            state="PROCESSING",
            meta={
                "status": "processing",
                "progress": 10,
                "message": "Processing started..."
            }
        )

        # Convert string to Enum
        processing_type_enum = TextProcessingType(processing_type)

        # --- RUN ASYNC FUNCTION IN SYNC CELERY TASK ---
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

        # Calcola metriche
        original_word_count = len(text.split())
        processed_word_count = len(processed_text.split())

        result = {
            "status": "completed",
            "progress": 100,
            "result": {
                "original_text": text,
                "processed_text": processed_text,
                "processing_type": processing_type,
                "word_count_original": original_word_count,
                "word_count_processed": processed_word_count,
                "processing_time": (
                    datetime.utcnow() - datetime.fromisoformat(self.request.eta or datetime.utcnow().isoformat())
                ).total_seconds() if self.request.eta else 0,
            },
            "message": "Text processing completed successfully"
        }

        logger.info(f"Task {task_id} completed successfully")
        return result

    except Exception as exc:
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
    
    Args:
        payment_data: {
            'amount': int,  # in centesimi
            'currency': str,
            'customer_email': str,
            'customer_name': str,
            'plan_type': str,
            'billing_details': dict,
            'metadata': dict
        }
    
    Returns:
        Dict con client_secret e customer_id
    """
    try:
        logger.info(f"Creating payment intent for {payment_data['customer_email']} - Task: {self.request.id}")
        
        # Validazione dati
        if not _validate_payment_data(payment_data):
            raise ValueError("Invalid payment data")
        
        # Cerca o crea customer
        customer = _get_or_create_customer(
            email=payment_data['customer_email'],
            name=payment_data['customer_name'],
            billing_details=payment_data.get('billing_details', {}),
            metadata=payment_data.get('metadata', {})
        )
        
        # Crea Payment Intent
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
            # Assumendo che create_payment_intent_record sia async
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
        # Retry per errori temporanei
        if e.http_status in [429, 500, 502, 503, 504]:
            raise self.retry(exc=e)
        raise e
        
    except Exception as e:
        logger.error(f"Error creating payment intent: {str(e)}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, name="process_payment_success_task", acks_late=True)
def process_payment_success_task(self, payment_data: Dict) -> Dict:
    """
    Task per processare il successo di un pagamento con Supabase.
    Gestisce anche il caso in cui payment_intent_id sia None (invoice senza PaymentIntent).
    """
    payment_intent_id = payment_data.get('payment_intent_id')
    customer_email = payment_data.get('customer_email')
    try:
        logger.info(f"Processing payment success for PI: {payment_intent_id} - Task: {self.request.id}")

        # Recupera PaymentIntent solo se esiste
        if payment_intent_id:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            if payment_intent.status != 'succeeded':
                logger.warning(f"Payment intent {payment_intent.id} status is {payment_intent.status}")
                raise ValueError(f"Payment not succeeded: {payment_intent.status}")

        # --- RUN ASYNC FUNCTIONS IN SYNC TASK ---
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Aggiorna stato pagamento
            loop.run_until_complete(
                payment_service.update_payment_intent_status(
                    stripe_payment_intent_id=payment_intent_id,
                    status='succeeded' if payment_intent_id else 'paid',
                    processing_status='completed',
                    completed_at=datetime.now()
                )
            )

            # Crea/aggiorna subscription
            subscription_result = loop.run_until_complete(
                payment_service.create_or_update_subscription(
                    email=customer_email,
                    stripe_customer_id=payment_data.get('customer_id'),
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

        logger.info(f"Payment success processed for {customer_email}")

        return {
            'success': True,
            'message': 'Payment processed successfully',
            'subscription_id': subscription_result.get('id')
        }

    except Exception as e:
        logger.error(f"Error processing payment success: {str(e)}")

        # Aggiorna status come fallito in Supabase
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    payment_service.update_payment_intent_status(
                        stripe_payment_intent_id=payment_intent_id,
                        status='processing_failed',
                        processing_status='failed'
                    )
                )
            finally:
                loop.close()
        except:
            pass

        raise e

@celery_app.task(bind=True, name="update_subscription_task", acks_late=True)
def update_subscription_task(self, subscription_data: Dict):
    """Task per aggiornare la subscription nel database"""
    try:
        logger.info(f"Updating subscription for {subscription_data['user_email']}")
        
        # Aggiorna il database
        result = update_user_subscription(subscription_data)
        
        if not result:
            raise ValueError("Failed to update subscription in database")
        
        logger.info(f"Subscription updated successfully for {subscription_data['user_email']}")
        return {'success': True}
        
    except Exception as e:
        logger.error(f"Error updating subscription: {str(e)}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, name="send_confirmation_email_task", acks_late=True)
def send_confirmation_email_task(self, email_data: Dict):
    """Task per inviare email di conferma"""
    try:
        logger.info(f"Sending confirmation email to {email_data['customer_email']}")
        
        result = send_payment_confirmation_email(
            to_email=email_data['customer_email'],
            plan_type=email_data['plan_type'],
            amount=email_data['amount'],
            payment_intent_id=email_data['payment_intent_id']
        )
        
        if not result:
            raise ValueError("Failed to send confirmation email")
        
        logger.info(f"Confirmation email sent to {email_data['customer_email']}")
        return {'success': True}
        
    except Exception as e:
        logger.error(f"Error sending confirmation email: {str(e)}")
        # Non fare retry se l'email fallisce - non bloccare il processo
        logger.warning("Email sending failed, but continuing with payment processing")
        return {'success': False, 'error': str(e)}

@celery_app.task(bind=True, name="handle_webhook_event_task", acks_late=True)
def handle_webhook_event_task(self, event_data: Dict):
    """Task per gestire eventi webhook da Stripe."""
    try:
        event_type = event_data.get('type')
        logger.info(f"Processing webhook event: {event_type}")
        
        if event_type == 'payment_intent.succeeded':
            invoice_obj = event_data['data']['object']

            # Email del cliente
            customer_email = invoice_obj.get('customer_email')
            if not customer_email and invoice_obj.get('customer'):
                customer = stripe.Customer.retrieve(invoice_obj['customer'])
                customer_email = customer.get('email')

            # ID del payment intent (può essere None)
            payment_intent_id = invoice_obj.get('payment_intent')

            # Importo pagato
            amount_paid = invoice_obj.get('amount_paid', 0) / 100  # da centesimi a unità

            # Metadata
            metadata = invoice_obj.get('metadata', {})

            task_id = str(uuid.uuid4())
            # Processa l'evento tramite task Celery
            process_payment_success_task.apply_async(
                kwargs={
                    'payment_data': {
                        'payment_intent_id': payment_intent_id,
                        'customer_id': invoice_obj.get('customer'),
                        'customer_email': customer_email,
                        'plan_type': metadata.get('plan_type'),
                        'amount': amount_paid
                    }
                },
                task_id=task_id,
                queue="payments"
            )

        elif event_type == 'payment_intent.payment_failed':
            payment_intent = event_data['data']['object']
            logger.warning(f"Payment failed: {payment_intent.get('id')}")
            # Qui puoi inviare un'email di notifica del fallimento

        return {'success': True, 'processed': event_type}

    except Exception as e:
        logger.error(f"Error handling webhook event: {str(e)}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, name="send_payment_failed_notification_task", acks_late=True)
def send_payment_failed_notification_task(self, failure_data: Dict):
    """Task per notificare pagamenti falliti"""
    try:
        logger.info(f"Sending payment failure notification to {failure_data['customer_email']}")
        
        # Implementa l'invio della notifica
        # Esempio: email, Slack notification, etc.
        
        return {'success': True}
        
    except Exception as e:
        logger.error(f"Error sending failure notification: {str(e)}")
        return {'success': False, 'error': str(e)}

@celery_app.task(bind=True, name="update_payment_analytics_task", acks_late=True)
def update_payment_analytics_task(self, analytics_data: Dict):
    """Task per aggiornare analytics giornaliere"""
    try:
        date = analytics_data['date']
        
        # Ottieni analytics esistenti per il giorno
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            existing = payment_service.client.table('payment_analytics')\
            .select('*')\
            .eq('date', date)\
            .execute()
        finally:
            loop.close()
        
        if existing.data:
            # Aggiorna analytics esistenti
            current = existing.data[0]
            updated_data = {
                'total_payments': current['total_payments'] + 1,
                'successful_payments': current['successful_payments'] + (1 if analytics_data['success'] else 0),
                'failed_payments': current['failed_payments'] + (0 if analytics_data['success'] else 1),
                'total_revenue': float(current['total_revenue']) + (analytics_data['amount'] if analytics_data['success'] else 0)
            }
            
            # Aggiorna revenue per piano
            if analytics_data['success']:
                if analytics_data['plan_type'] == 'monthly':
                    updated_data['revenue_monthly_plans'] = float(current['revenue_monthly_plans']) + analytics_data['amount']
                else:
                    updated_data['revenue_yearly_plans'] = float(current['revenue_yearly_plans']) + analytics_data['amount']
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                payment_service.client.table('payment_analytics')\
                .update(updated_data)\
                .eq('date', date)\
                .execute()
            finally:
                loop.close()
        else:
            # Crea nuovo record
            new_data = {
                'date': date,
                'total_payments': 1,
                'successful_payments': 1 if analytics_data['success'] else 0,
                'failed_payments': 0 if analytics_data['success'] else 1,
                'total_revenue': analytics_data['amount'] if analytics_data['success'] else 0,
                'revenue_monthly_plans': analytics_data['amount'] if (analytics_data['success'] and analytics_data['plan_type'] == 'monthly') else 0,
                'revenue_yearly_plans': analytics_data['amount'] if (analytics_data['success'] and analytics_data['plan_type'] == 'yearly') else 0,
            }
        
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                payment_service.client.table('payment_analytics')\
                .insert(new_data)\
                .execute()
            finally:
                loop.close()        

        logger.info(f"Analytics updated for {date}")
        return {'success': True}
        
    except Exception as e:
        logger.error(f"Error updating analytics: {str(e)}")
        raise self.retry(exc=e)

@celery_app.task(bind=True, name="cleanup_old_payment_intents_task", acks_late=True)
def cleanup_old_payment_intents_task():
    """Task periodico per pulire vecchi payment intent"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            deleted_count = payment_service.cleanup_old_payment_intents(days=7)
            logger.info(f"Cleaned up {deleted_count} old payment intents")
            return {'deleted_count': deleted_count}
        finally:
            loop.close()             
    except Exception as e:
        logger.error(f"Error in cleanup task: {str(e)}")

@celery_app.task(bind=True, name="check_expiring_subscriptions_task", acks_late=True)
def check_expiring_subscriptions_task():
    """Task per controllare subscription in scadenza"""
    try:

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            expiring = payment_service.get_expiring_subscriptions(days_ahead=7)
        finally:
            loop.close()
        
        for subscription in expiring:
            # Invia notifica di scadenza
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

@celery_app.task(bind=True, name="send_expiring_subscription_notification_task", acks_late=True)
def send_expiring_subscription_notification_task(self, notification_data: Dict):
    """Task per inviare notifiche di scadenza subscription"""
    try:
        logger.info(f"Sending expiration notification to {notification_data['customer_email']}")
        
        # Implementa l'invio della notifica di scadenza
        # Esempio: email reminder, push notification, etc.
        
        return {'success': True}
        
    except Exception as e:
        logger.error(f"Error sending expiration notification: {str(e)}")
        return {'success': False, 'error': str(e)}

@celery_app.task(bind=True, name="payment_health_check_task", acks_late=True)
def payment_health_check_task():
    """Task per controllare la salute del sistema di pagamenti"""
    try:
        # Controlla connessione Stripe
        stripe.Account.retrieve()
        
        # Controlla connessione Supabase
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            test_response = payment_service.client.table('user_subscriptions')\
            .select('count')\
            .limit(1)\
            .execute()
        finally:
            loop.close()   
        
        # Ottieni statistiche rapide
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            analytics = payment_service.get_payment_analytics(days=1)
        finally:
            loop.close()   
        
        health_status = {
            'stripe_connection': True,
            'supabase_connection': True,
            'last_24h_payments': analytics.get('total_payments', 0),
            'last_24h_revenue': analytics.get('total_revenue', 0),
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
        # Cerca customer esistente
        existing_customers = stripe.Customer.list(email=email, limit=1)
        
        if existing_customers.data:
            customer = existing_customers.data[0]
            logger.info(f"Found existing customer: {customer.id}")
            return customer
        
        # Crea nuovo customer
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

def _calculate_end_date(plan_type: str) -> datetime:
    """Calcola la data di fine subscription"""
    now = datetime.now()
    
    if plan_type == 'yearly':
        return now + timedelta(days=365)
    else:  # monthly
        return now + timedelta(days=30)
