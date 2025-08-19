# config/stripe_config.py
import os
import stripe
from app.core.config import Settings

# Inizializza Stripe
stripe.api_key = Settings.STRIPE_SECRET_KEY

class StripeConfig:
    """Configurazione centralizzata per Stripe"""
    
    API_VERSION = '2023-10-16'
    
    # Importi minimi
    MIN_AMOUNT = 50  # 50 centesimi
    
    # Valute supportate
    SUPPORTED_CURRENCIES = ['eur', 'usd', 'gbp']

    STRIPE_WEBHOOK_SECRET = Settings.STRIPE_WEBHOOK_SECRET
    STRIPE_PUBLIC_KEY = Settings.STRIPE_PUBLIC_KEY
    STRIPE_SECRET_KEY = Settings.STRIPE_SECRET_KEY

    # Piani disponibili
    PLANS = {
        'monthly': {
            'price': 500,  # 5.00 EUR in centesimi
            'currency': 'eur',
            'interval': 'month'
        },
        'yearly': {
            'price': 4800,  # 48.00 EUR in centesimi (sconto 20%)
            'currency': 'eur', 
            'interval': 'year'
        }
    }
    
    @classmethod
    def get_plan_amount(cls, plan_type: str) -> int:
        """Restituisce l'importo per il piano specificato"""
        return cls.PLANS.get(plan_type, {}).get('price', 0)
    
    @classmethod
    def is_valid_plan(cls, plan_type: str) -> bool:
        """Verifica se il piano è valido"""
        return plan_type in cls.PLANS