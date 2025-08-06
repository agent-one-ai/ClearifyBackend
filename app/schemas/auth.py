from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, validator

class GoogleTokenRequest(BaseModel):
    token: str

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    subscription_tier: str = "free"
    credits_remaining: int = 100
    created_at: datetime
    updated_at: datetime

class AuthResponse(BaseModel):
    user: UserResponse
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600

class GoogleAuthUrlResponse(BaseModel):
    auth_url: str

class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str

class UserRegisterRequest(BaseModel):
    firstName: str
    lastName: str
    email: EmailStr
    password: str
    confirmPassword: str
    agreeTerms: bool
    
    @validator('firstName')
    def validate_first_name(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError('Il nome deve essere di almeno 2 caratteri')
        return v.strip()
    
    @validator('lastName')
    def validate_last_name(cls, v):
        if not v or len(v.strip()) < 2:
            raise ValueError('Il cognome deve essere di almeno 2 caratteri')
        return v.strip()
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('La password deve essere di almeno 8 caratteri')
        return v
    
    @validator('confirmPassword')
    def validate_confirm_password(cls, v, values):
        if 'password' in values and v != values['password']:
            raise ValueError('Le password non corrispondono')
        return v
    
    @validator('agreeTerms')
    def validate_agree_terms(cls, v):
        if not v:
            raise ValueError('Devi accettare i termini di servizio')
        return v
