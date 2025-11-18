from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging
from uuid import UUID

from app.core.supabase_client import supabase_client
from postgrest import APIError

logger = logging.getLogger(__name__)

class SupabasePaymentService:
    """Service per gestire pagamenti con Supabase"""
    
    def __init__(self):
        self.client = supabase_client  # Usa admin client per operazioni privilegiate
    
    async def create_payment_intent_record(
        self, 
        stripe_payment_intent_id: str,
        stripe_customer_id: str,
        amount: int,
        currency: str,
        plan_type: str,
        customer_email: str,
        customer_name: str = None,
        billing_details: Dict = None,
        celery_task_id: str = None
    ) -> Dict:
        """Crea un record per il payment intent"""
        try:
            data = {
                'stripe_payment_intent_id': stripe_payment_intent_id,
                'stripe_customer_id': stripe_customer_id,
                'amount': amount,
                'currency': currency,
                'status': 'requires_payment_method',
                'plan_type': plan_type,
                'customer_email': customer_email,
                'customer_name': customer_name,
                'billing_details': billing_details or {},
                'celery_task_id': celery_task_id,
                'processing_status': 'pending'
            }
            
            response = self.client.table('payment_intents').insert(data).execute()
            
            if response.data:
                logger.info(f"Payment intent record created: {stripe_payment_intent_id}")
                return response.data[0]
            else:
                raise Exception("No data returned from insert")
                
        except APIError as e:
            logger.error(f"Error creating payment intent record: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error creating payment intent record: {e}")
            raise e
    
    async def update_payment_intent_status(
        self, 
        stripe_payment_intent_id: str, 
        status: str,
        processing_status: str = None,
        completed_at: datetime = None
    ) -> bool:
        """Aggiorna lo status di un payment intent"""
        try:
            update_data = {'status': status}
            
            if processing_status:
                update_data['processing_status'] = processing_status
            
            if completed_at:
                update_data['completed_at'] = completed_at.isoformat()
            elif status == 'succeeded':
                update_data['completed_at'] = datetime.utcnow().isoformat()
            
            response = self.client.table('payment_intents')\
                .update(update_data)\
                .eq('stripe_payment_intent_id', stripe_payment_intent_id)\
                .execute()
            
            logger.info(f"Payment intent status updated: {stripe_payment_intent_id} -> {status}")
            return True
            
        except APIError as e:
            logger.error(f"Error updating payment intent status: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error updating payment intent: {e}")
            return False
    
    async def create_or_update_subscription(
        self,
        user_id: UUID = None,
        email: str = None,
        stripe_customer_id: str = None,
        stripe_payment_intent_id: str = None,
        plan_type: str = None,
        status: str = "active",
        amount_paid: float = None,
        currency: str = "EUR",
        start_date: datetime = None,
        end_date: datetime = None,
        metadata: Dict = None
    ) -> Dict:
        """Crea o aggiorna una subscription utente e aggiorna il tier"""
        try:
            if not email:
                raise ValueError("Email is required")
            
            # Calcola le date se non fornite
            if not start_date:
                start_date = datetime.utcnow()
            
            if not end_date:
                if plan_type == "yearly":
                    end_date = start_date + timedelta(days=365)
                else:  # monthly
                    end_date = start_date + timedelta(days=30)
            
            # Controlla se esiste già una subscription attiva
            existing_response = self.client.table("user_subscriptions")\
                .select("*")\
                .eq("email", email)\
                .execute()
            
            subscription_data = {
                "email": email,
                "stripe_customer_id": stripe_customer_id,
                "stripe_payment_intent_id": stripe_payment_intent_id,
                "plan_type": plan_type,
                "status": status,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "last_payment_date": datetime.utcnow().isoformat(),
                "amount_paid": amount_paid,
                "currency": currency,
                "metadata": metadata or {}
            }
            
            if user_id:
                subscription_data["user_id"] = str(user_id)
            
            # Se esiste una subscription attiva
            if existing_response.data:
                existing_sub = existing_response.data[0]
                logger.info(f"User Exists")
                if existing_sub["plan_type"] != plan_type:
                    logger.info(f"Insert new record")
                    # Upgrade/downgrade → cancella la vecchia e crea nuova
                    await self._cancel_subscription(existing_sub["id"])
                    response = self.client.table("user_subscriptions")\
                        .insert(subscription_data)\
                        .execute()
                else:
                    logger.info(f"Update")
                    # Aggiorna la subscription esistente
                    response = self.client.table("user_subscriptions")\
                        .update(subscription_data)\
                        .eq("id", existing_sub["id"])\
                        .execute()
            else:
                logger.info(f"Inserisco il record perche non esiste")
                # Nessuna subscription attiva → crea nuova
                response = self.client.table("user_subscriptions")\
                    .insert(subscription_data)\
                    .execute()
            
            if not response.data:
                raise Exception("No data returned from subscription operation")
            
            subscription = response.data[0]

            # Aggiorna sempre l'utente a "premium" se ha una subscription attiva
            self.client.table("users")\
                .update({"subscription_tier": "premium"})\
                .eq("email", email)\
                .execute()
            
            logger.info(f"Subscription created/updated for {email} - Plan: {plan_type}")
            return subscription

        except APIError as e:
            logger.error(f"Error creating/updating subscription: {e}")
            raise e
        except Exception as e:
            logger.error(f"Unexpected error with subscription: {e}")
            raise e

    
    async def _cancel_subscription(self, subscription_id: str) -> bool:
        """Cancella una subscription"""
        try:
            response = self.client.table('user_subscriptions')\
                .update({
                    'status': 'canceled',
                    'canceled_at': datetime.utcnow().isoformat()
                })\
                .eq('id', subscription_id)\
                .execute()
            
            return True
        except Exception as e:
            logger.error(f"Error canceling subscription {subscription_id}: {e}")
            return False
    
    async def get_user_subscription(self, email: str) -> Optional[Dict]:
        """Ottiene la subscription attiva di un utente"""
        try:
            response = self.client.table('user_subscriptions')\
                .select('*')\
                .eq('email', email)\
                .eq('status', 'active')\
                .gte('end_date', datetime.utcnow().isoformat())\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            if response.data:
                return response.data[0]
            return None
            
        except APIError as e:
            logger.error(f"Error getting user subscription: {e}")
            return None
    
    async def log_webhook_event(
        self,
        stripe_event_id: str,
        event_type: str,
        event_data: Dict,
        celery_task_id: str = None
    ) -> Dict:
        """Logga un evento webhook"""
        try:
            data = {
                'stripe_event_id': stripe_event_id,
                'event_type': event_type,
                'event_data': event_data,
                'celery_task_id': celery_task_id,
                'processed': False,
                'processing_status': 'pending'
            }
            
            response = self.client.table('stripe_webhook_events')\
                .insert(data)\
                .execute()
            
            if response.data:
                logger.info(f"Webhook event logged: {stripe_event_id}")
                return response.data[0]
            
        except APIError as e:
            logger.error(f"Error logging webhook event: {e}")
            raise e
    
    async def mark_webhook_processed(
        self,
        stripe_event_id: str,
        success: bool = True,
        error_message: str = None
    ) -> bool:
        """Marca un webhook come processato"""
        try:
            update_data = {
                'processed': success,
                'processing_status': 'completed' if success else 'failed',
                'processed_at': datetime.utcnow().isoformat()
            }
            
            if error_message:
                update_data['error_message'] = error_message
            
            response = self.client.table('stripe_webhook_events')\
                .update(update_data)\
                .eq('stripe_event_id', stripe_event_id)\
                .execute()
            
            return True
            
        except Exception as e:
            logger.error(f"Error marking webhook as processed: {e}")
            return False
    
    async def get_payment_analytics(self, days: int = 30) -> Dict:
        """Ottiene analytics sui pagamenti"""
        try:
            # Usa la vista che abbiamo creato
            response = self.client.table('payment_dashboard')\
                .select('*')\
                .gte('payment_date', (datetime.utcnow() - timedelta(days=days)).date())\
                .execute()
            
            if response.data:
                # Calcola totali
                total_revenue = sum(row['revenue'] or 0 for row in response.data)
                total_payments = sum(row['total_payments'] for row in response.data)
                total_successful = sum(row['successful_payments'] for row in response.data)
                
                return {
                    'total_revenue': total_revenue,
                    'total_payments': total_payments,
                    'successful_payments': total_successful,
                    'success_rate': (total_successful / total_payments * 100) if total_payments > 0 else 0,
                    'daily_data': response.data
                }
            
            return {
                'total_revenue': 0,
                'total_payments': 0,
                'successful_payments': 0,
                'success_rate': 0,
                'daily_data': []
            }
            
        except Exception as e:
            logger.error(f"Error getting payment analytics: {e}")
            return {}
    
    async def get_expiring_subscriptions(self, days_ahead: int = 7) -> List[Dict]:
        """Ottiene subscription che scadono presto"""
        try:
            cutoff_date = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat()
            
            response = self.client.table('user_subscriptions')\
                .select('*')\
                .eq('status', 'active')\
                .lte('end_date', cutoff_date)\
                .execute()
            
            return response.data or []
            
        except Exception as e:
            logger.error(f"Error getting expiring subscriptions: {e}")
            return []
    
    async def cleanup_old_payment_intents(self, days: int = 30) -> int:
        """Pulisce vecchi payment intent non completati"""
        try:
            cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
            
            # Prima ottieni i record da eliminare
            response = self.client.table('payment_intents')\
                .select('id')\
                .neq('status', 'succeeded')\
                .lt('created_at', cutoff_date)\
                .execute()
            
            if not response.data:
                return 0
            
            # Elimina i record
            ids_to_delete = [record['id'] for record in response.data]
            
            delete_response = self.client.table('payment_intents')\
                .delete()\
                .in_('id', ids_to_delete)\
                .execute()
            
            deleted_count = len(response.data)
            logger.info(f"Cleaned up {deleted_count} old payment intents")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up payment intents: {e}")
            return 0

# Istanza globale del service
payment_service = SupabasePaymentService()