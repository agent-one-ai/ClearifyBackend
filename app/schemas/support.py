from typing import Optional, Dict
from datetime import datetime
from pydantic import BaseModel, EmailStr, validator

class UserInfo(BaseModel):
    subscription_tier: Optional[str] = None
    credits_remaining: Optional[int] = None
    created_at: Optional[str] = None

class SupportTicketRequest(BaseModel):
    name: str
    email: EmailStr
    category: str  # general, technical, billing, feature
    priority: str  # low, medium, high, urgent
    subject: str
    message: str
    attachScreenshot: bool = False
    userAgent: str
    timestamp: str
    userId: Optional[str] = None
    userInfo: Optional[UserInfo] = None

class SupportTicketResponse(BaseModel):
    success: bool
    message: str
    ticket_id: str
    expected_response_time: str





