from typing import Optional, Dict
from datetime import datetime
from pydantic import BaseModel, EmailStr, validator


class BillingAddress(BaseModel):
    city: str
    country: str
    line1: str
    postal_code: str

class BillingDetails(BaseModel):
    name: str
    email: EmailStr
    address: BillingAddress

class Metadata(BaseModel):
    plan: str
    customer_name: str
    customer_email: EmailStr
    company: str = ""

class CreatePaymentIntentRequest(BaseModel):
    amount: int
    currency: str = "eur"
    billing_details: BillingDetails
    metadata: Metadata

class PaymentSuccessRequest(BaseModel):
    paymentIntentId: str
    customerId: str
    customerEmail: EmailStr
    plan: str
    amount: float





