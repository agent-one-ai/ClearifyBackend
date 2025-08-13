from fastapi import APIRouter, HTTPException,Request, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import requests
from datetime import datetime, timedelta
import jwt
from passlib.context import CryptContext
from jose import JWTError, jwt
import uuid
from app.core.config import settings
from app.core.supabase_client import supabase_client
from app.schemas.auth import (
    GoogleTokenRequest, 
    AuthResponse, 
    UserResponse,
    GoogleAuthUrlResponse,
    UserRegisterRequest,
    UserLoginRequest
)
import time
from app.core.logging import SupabaseAPILogger, log_request, log_security_event

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

api_logger = SupabaseAPILogger(supabase_client)

@router.get("/google/url", response_model=GoogleAuthUrlResponse)
async def get_google_auth_url(request: Request):
    """Generate Google OAuth URL for frontend redirect"""
    start_time = time.time()
    
    try:
        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={settings.GOOGLE_CLIENT_ID}&"
            f"redirect_uri={settings.FRONTEND_URL}/auth/callback&"
            "response_type=code&"
            "scope=openid email profile&"
            "access_type=offline&"
            "prompt=consent"
        )
        
        response = GoogleAuthUrlResponse(auth_url=auth_url)
        
        # Log della richiesta
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            additional_data={"action": "google_auth_url_generated"}
        )
        
        return response
        
    except Exception as e:
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            error=str(e)
        )
        raise


    """Handle Google OAuth callback"""
    
    try:
        body = await request.json()
        code = body.get("code")
        
        if not code:
            raise HTTPException(status_code=400, detail="Authorization code missing")
        
        # Exchange code for tokens
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": f"{settings.FRONTEND_URL}/auth/callback"
        }
        
        token_response = requests.post(token_url, data=token_data)
        token_response.raise_for_status()
        tokens = token_response.json()
        
        # Verify ID token
        id_token_jwt = tokens.get("id_token")
        if not id_token_jwt:
            raise HTTPException(status_code=400, detail="ID token missing")
        
        # Decode and verify Google ID token
        try:
            idinfo = id_token.verify_oauth2_token(
                id_token_jwt, 
                google_requests.Request(), 
                settings.GOOGLE_CLIENT_ID
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid ID token")
        
        # Extract user info
        google_id = idinfo.get("sub")
        email = idinfo.get("email")
        name = idinfo.get("name", "")
        picture = idinfo.get("picture", "")
        
        if not email or not google_id:
            raise HTTPException(status_code=400, detail="Email or Google ID missing")
        
        # Check if user exists in Supabase
        user_response = supabase_client.table("users").select("*").eq("email", email).execute()
        
        if user_response.data:
            # User exists, update login time
            user_data = user_response.data[0]
            supabase_client.table("users").update({
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", user_data["id"]).execute()
        else:
            # Create new user
            new_user = {
                "email": email,
                "full_name": name,
                "avatar_url": picture,
                "subscription_tier": "free",
                "credits_remaining": 100,
                "google_id": google_id
            }
            
            user_response = supabase_client.table("users").insert(new_user).execute()
            if not user_response.data:
                raise HTTPException(status_code=500, detail="Failed to create user")
            user_data = user_response.data[0]
        
        # Generate JWT token
        access_token = create_access_token({"sub": email, "user_id": user_data["id"]})
        
        # Return user data and token
        user_obj = UserResponse(**user_data)
        return AuthResponse(
            user=user_obj,
            access_token=access_token,
            token_type="bearer",
            expires_in=3600
        )
        
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Google API error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")

@router.post("/google/callback")
async def google_callback(request: Request):
    """Handle Google OAuth callback"""
    start_time = time.time()
    user_id = None
    
    try:
        body = await request.json()
        code = body.get("code")
        
        if not code:
            await log_security_event(
                supabase_client=supabase_client,
                event="missing_auth_code",
                client_ip=api_logger._get_client_ip(request),
                details="Authorization code missing in Google callback"
            )
            raise HTTPException(status_code=400, detail="Authorization code missing")
        
        # Exchange code for tokens
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": f"{settings.FRONTEND_URL}/auth/callback"
        }
        
        token_response = requests.post(token_url, data=token_data)
        token_response.raise_for_status()
        tokens = token_response.json()
        
        # Verify ID token
        id_token_jwt = tokens.get("id_token")
        if not id_token_jwt:
            await log_security_event(
                supabase_client=supabase_client,
                event="missing_id_token",
                client_ip=api_logger._get_client_ip(request),
                details="ID token missing in Google response"
            )
            raise HTTPException(status_code=400, detail="ID token missing")
        
        # Decode and verify Google ID token
        try:
            idinfo = id_token.verify_oauth2_token(
                id_token_jwt, 
                google_requests.Request(), 
                settings.GOOGLE_CLIENT_ID
            )
        except ValueError:
            await log_security_event(
                supabase_client=supabase_client,
                event="invalid_google_token",
                client_ip=api_logger._get_client_ip(request),
                details="Invalid Google ID token"
            )
            raise HTTPException(status_code=400, detail="Invalid ID token")
        
        # Extract user info
        google_id = idinfo.get("sub")
        email = idinfo.get("email")
        name = idinfo.get("name", "")
        picture = idinfo.get("picture", "")
        
        if not email or not google_id:
            raise HTTPException(status_code=400, detail="Email or Google ID missing")
        
        # Check if user exists in Supabase
        user_response = supabase_client.table("users").select("*").eq("email", email).execute()
        
        if user_response.data:
            # User exists, update login time
            user_data = user_response.data[0]
            user_id = user_data["id"]
            supabase_client.table("users").update({
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", user_data["id"]).execute()
            
            action = "google_login_existing_user"
        else:
            # Create new user
            user_id = str(uuid.uuid4())
            new_user = {
                "id": user_id,
                "email": email,
                "full_name": name,
                "avatar_url": picture,
                "subscription_tier": "free",
                "credits_remaining": 100,
                "google_id": google_id
            }
            
            user_response = supabase_client.table("users").insert(new_user).execute()
            if not user_response.data:
                raise HTTPException(status_code=500, detail="Failed to create user")
            user_data = user_response.data[0]
            
            action = "google_signup_new_user"
        
        # Generate JWT token
        access_token = create_access_token({"sub": email, "user_id": user_data["id"]})
        
        # Log successful authentication
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            additional_data={
                "action": action,
                "email": email,
                "authentication_method": "google_oauth"
            }
        )
        
        # Return user data and token
        user_obj = UserResponse(**user_data)
        return AuthResponse(
            user=user_obj,
            access_token=access_token,
            token_type="bearer",
            expires_in=3600
        )
        
    except requests.RequestException as e:
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            error=f"Google API error: {str(e)}"
        )
        raise HTTPException(status_code=400, detail=f"Google API error: {str(e)}")
    except Exception as e:
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            error=f"Authentication error: {str(e)}"
        )
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")

@router.post("/google/token", response_model=AuthResponse)
async def google_token_login(token_request: GoogleTokenRequest):
    """Direct Google ID token verification (alternative method)"""
    
    try:
        # Verify Google ID token directly
        idinfo = id_token.verify_oauth2_token(
            token_request.token, 
            google_requests.Request(), 
            settings.GOOGLE_CLIENT_ID
        )
        
        google_id = idinfo.get("sub")
        email = idinfo.get("email")
        name = idinfo.get("name", "")
        picture = idinfo.get("picture", "")
        
        if not email or not google_id:
            raise HTTPException(status_code=400, detail="Invalid token data")
        
        # Same user creation/update logic as above
        user_response = supabase_client.table("users").select("*").eq("email", email).execute()
        
        if user_response.data:
            user_data = user_response.data[0]
            supabase_client.table("users").update({
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", user_data["id"]).execute()
        else:
            new_user = {
                "email": email,
                "full_name": name,
                "avatar_url": picture,
                "google_id": google_id,
                "subscription_tier": "free",
                "credits_remaining": 100
            }
            
            user_response = supabase_client.table("users").insert(new_user).execute()
            if not user_response.data:
                raise HTTPException(status_code=500, detail="Failed to create user")
            user_data = user_response.data[0]
        
        access_token = create_access_token({"sub": email, "user_id": user_data["id"]})
        
        user_obj = UserResponse(**user_data)
        return AuthResponse(
            user=user_obj,
            access_token=access_token,
            token_type="bearer",
            expires_in=3600
        )
        
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Google token")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Authentication error: {str(e)}")

@router.post("/register", response_model=AuthResponse)
async def register_user(user_data: UserRegisterRequest, request: Request):
    """Registrazione nuovo utente"""
    start_time = time.time()
    user_id = None

    try:
        # Controlla se l'utente esiste già
        existing_user = supabase_client.table("users").select("email").eq("email", user_data.email).execute()
        
        if existing_user.data:
            await log_security_event(
                supabase_client=supabase_client,
                event="registration_attempt_existing_email",
                client_ip=api_logger._get_client_ip(request),
                details=f"Registration attempt with existing email: {user_data.email}"
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un utente con questa email esiste già"
            )
        
        # Hash della password
        hashed_password = hash_password(user_data.password)
        
        # Crea il nuovo utente        
        user_id = str(uuid.uuid4())
        new_user_data = {
            "id": user_id,
            "email": user_data.email,
            "full_name": f"{user_data.firstName} {user_data.lastName}",
            "password_hash": hashed_password,
            "subscription_tier": "free",
            "credits_remaining": 100,
            "avatar_url": None,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "google_id": None
        }
        
        # Inserisci nel database
        result = supabase_client.table("users").insert(new_user_data).execute()
        
        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Errore durante la creazione dell'utente"
            )
        
        user_record = result.data[0]
        user_record.pop('password_hash', None)
        
        # Crea JWT token
        access_token = create_access_token(
            data={"sub": user_record["email"], "user_id": user_record["id"]}
        )
        
        # Log successful registration
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            additional_data={
                "action": "user_registration",
                "email": user_data.email,
                "authentication_method": "password"
            }
        )

        user_response = UserResponse(**user_record)
        
        return AuthResponse(
            user=user_response,
            access_token=access_token,
            token_type="bearer",
            expires_in=3600
        )
        
    except HTTPException:
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            error="Registration failed"
        )
        raise
    except Exception as e:
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            error=f"Registration error: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore durante la registrazione: {str(e)}"
        )

@router.post("/login", response_model=AuthResponse)
async def login_user(login_data: UserLoginRequest, request: Request):
    """Login utente esistente"""
    start_time = time.time()
    user_id = None
    
    try:
        # Trova l'utente nel database
        user_result = supabase_client.table("users").select("*").eq("email", login_data.email).execute()
        
        if not user_result.data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email o password non corretti"
            )
        
        user_record = user_result.data[0]
        
        # Verifica la password
        if not verify_password(login_data.password, user_record["password_hash"]):
            process_time = (time.time() - start_time) * 1000
        
            # Log fallimenti di login come eventi di sicurezza
            await log_security_event(
                supabase_client=supabase_client,
                event="login_failure",
                client_ip=api_logger._get_client_ip(request),
                details=f"Login failed for email: {login_data.email}",
                user_id=user_id
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email o password non corretti"
            )
        
        # Aggiorna ultima connessione
        supabase_client.table("users").update({
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", user_record["id"]).execute()
        
        user_record.pop('password_hash', None)
        
        # Crea JWT token
        access_token = create_access_token(
            data={"sub": user_record["email"], "user_id": user_record["id"]}
        )
        
        user_response = UserResponse(**user_record)
        
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            additional_data={
                "action": "user_login",
                "email": login_data.email,
                "authentication_method": "password"
            }
        )

        return AuthResponse(
            user=user_response,
            access_token=access_token,
            token_type="bearer",
            expires_in=3600
        )
        
    except HTTPException:
        raise
    except Exception as e:        
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            error=f"Login error: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore durante il login: {str(e)}"
        )

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt