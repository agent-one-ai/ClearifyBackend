from typing import Optional, Dict, List
from datetime import datetime
from pydantic import BaseModel, EmailStr, validator

class UserInfo(BaseModel):
    subscription_tier: Optional[str] = None
    credits_remaining: Optional[int] = None
    created_at: Optional[str] = None

class SupportTicketRequest(BaseModel):
    action: str
    team: str
    customer_email: str
    category: str
    priority: str
    title: str
    description: str
    original_message: str
    needScreenshots: bool
    labels: List[str]

class SupportTicketResponse(BaseModel):
    success: bool
    message: str
    value: str




