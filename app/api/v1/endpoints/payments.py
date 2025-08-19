# api/payment_endpoints.py (FastAPI example)
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from typing import Dict, Optional
import stripe
import uuid
import hmac
import hashlib
import logging
from app.schemas.payment import CreatePaymentIntentRequest, PaymentSuccessRequest, BillingDetails

from app.workers.tasks import (
    create_payment_intent_task,
    process_payment_success_task,
    handle_webhook_event_task
)
from app.core.stripe_config import StripeConfig


router = APIRouter()

# Configurazione logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

@router.post("/create-payment-intent")
async def create_payment_intent(request: CreatePaymentIntentRequest):
    """
    Endpoint per creare un Payment Intent tramite task Celery
    """
    try:
        # Validazione del piano
        if not StripeConfig.is_valid_plan(request.metadata.plan):
            raise HTTPException(status_code=400, detail="Invalid plan type")
        
        # Validazione importo
        expected_amount = StripeConfig.get_plan_amount(request.metadata.plan)
        if request.amount != expected_amount:
            raise HTTPException(
                status_code=400, 
                detail=f"Amount mismatch. Expected {expected_amount}, got {request.amount}"
            )
        
        # Prepara i dati per il task
        payment_data = {
            "amount": request.amount,
            "currency": request.currency,
            "customer_email": request.metadata.customer_email,
            "customer_name": request.metadata.customer_name,
            "plan_type": request.metadata.plan,
            "billing_details": request.billing_details.dict(),
            "metadata": request.metadata.dict() or {}
        }

        task_id = str(uuid.uuid4())

        # Processa l'evento tramite task Celery
        task = create_payment_intent_task.apply_async(
            args=[
                payment_data
            ],
            task_id=task_id,
            queue="payments"
        )
        
        # Aspetta il risultato del task (con timeout)
        try:
            result = task.get(timeout=30)  # 30 secondi di timeout
        except Exception as e:
            logger.error(f"Task failed: {str(e)}")
            raise HTTPException(status_code=500, detail="Payment intent creation failed")
        
        if not result.get('success'):
            raise HTTPException(status_code=500, detail="Failed to create payment intent")
        
        return JSONResponse({
            "client_secret": result['client_secret'],
            "customer_id": result['customer_id'],
            "payment_intent_id": result['payment_intent_id']
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating payment intent: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/payment-success")
async def payment_success(request: PaymentSuccessRequest, background_tasks: BackgroundTasks):
    """
    Endpoint chiamato dal frontend quando il pagamento è completato
    """
    try:
        # Prepara i dati per il task
        payment_data = {
            "payment_intent_id": request.paymentIntentId,
            "customer_id": request.customerId,
            "customer_email": request.customerEmail,
            "plan_type": request.plan,
            "amount": request.amount
        }
        
        # Avvia il task in background (non aspettiamo il risultato)
        # task = process_payment_success_task.apply_async(payment_data)

        task_id = str(uuid.uuid4())

        # Processa l'evento tramite task Celery
        task = process_payment_success_task.apply_async(
            args=[
                payment_data
            ],
            task_id=task_id,
            queue="payments"
        )

        logger.info(task)
        
        return JSONResponse({
            "success": True,
            "message": "Payment is being processed"
        })
        
    except Exception as e:
        logger.error(f"Error processing payment success: {str(e)}")
        raise HTTPException(status_code=500, detail="Error processing payment")

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """
    Endpoint per ricevere webhook da Stripe
    """
    try:
        body = await request.body()
        signature = request.headers.get('stripe-signature')
        
        #logger.info(f'Headers found: {body}, {signature}, {StripeConfig.STRIPE_WEBHOOK_SECRET}')

        if not signature:
            logger.error("No Stripe signature found")
            raise HTTPException(status_code=400, detail="No signature found")
        
        if not StripeConfig.STRIPE_WEBHOOK_SECRET:
            logger.error("Webhook secret not configured")
            raise HTTPException(status_code=500, detail="Webhook not configured")
        
        # Verifica la firma del webhook
        try:
            event = stripe.Webhook.construct_event(
                body, signature, StripeConfig.STRIPE_WEBHOOK_SECRET
            )
        except ValueError as e:
            logger.error(f"Invalid payload: {e}")
            raise HTTPException(status_code=400, detail="Invalid payload")
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid signature: {e}")
            raise HTTPException(status_code=400, detail="Invalid signature")
        
        task_id = str(uuid.uuid4())

        # Processa l'evento tramite task Celery
        task = handle_webhook_event_task.apply_async(
            args=[
                event
            ],
            task_id=task_id,
            queue="webhooks"
        )
        
        return JSONResponse({"status": "success"})
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

@router.get("/plans")
async def get_plans():
    """
    Endpoint per ottenere i piani disponibili
    """
    return JSONResponse({
        "plans": StripeConfig.PLANS
    })

@router.get("/task-status/{task_id}")
async def get_task_status(task_id: str):
    """
    Endpoint per controllare lo stato di un task Celery
    """
    try:
        from celery_app import celery_app
        
        task_result = celery_app.AsyncResult(task_id)
        
        if task_result.state == 'PENDING':
            response = {
                'state': task_result.state,
                'status': 'Task is waiting to be processed'
            }
        elif task_result.state == 'SUCCESS':
            response = {
                'state': task_result.state,
                'result': task_result.result
            }
        else:  # FAILURE
            response = {
                'state': task_result.state,
                'error': str(task_result.info)
            }
        
        return JSONResponse(response)
        
    except Exception as e:
        logger.error(f"Error checking task status: {str(e)}")
        raise HTTPException(status_code=500, detail="Error checking task status")