from fastapi import APIRouter, HTTPException, Request, Depends, status, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import requests
from datetime import datetime, timedelta
import uuid
from passlib.context import CryptContext
from jose import JWTError, jwt

from app.core.config import settings
from app.core.supabase_client import supabase_client
from app.core.auth import get_current_user
from app.schemas.auth import (
    GoogleTokenRequest,
    AuthResponse,
    UserResponse,
    GoogleAuthUrlResponse,
    UserRegisterRequest,
    UserLoginRequest
)
from app.core.logging import SupabaseAPILogger, log_request, log_security_event
import time

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
api_logger = SupabaseAPILogger(supabase_client)

# ================================
# UTILITY FUNCTIONS MODIFICATE
# ================================

def serialize_datetime_fields(data: dict) -> dict:
    """Converte tutti i campi datetime in stringhe ISO"""
    result = data.copy()
    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result

def create_access_token(data: dict, expires_delta: int = 86400):  # Per ora metto 24 ore, valutiamo
    """Token di accesso di breve durata"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(seconds=expires_delta)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm='HS256')
    return encoded_jwt

def create_refresh_token(data: dict, expires_delta: int = 604800):  # 7 giorni
    """Token di refresh di lunga durata"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(seconds=expires_delta)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm='HS256')
    return encoded_jwt

def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    """Imposta i cookie httpOnly per i token"""
    # Access token - breve durata, httpOnly, secure
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,  # Non accessibile da JavaScript
        secure=True,    # Solo HTTPS in produzione
        samesite="strict",
        max_age=900,    # 15 minuti
        path="/"
    )
    
    # Refresh token - lunga durata, httpOnly, secure
    response.set_cookie(
        key="refresh_token", 
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="strict", 
        max_age=604800,  # 7 giorni
        path="/auth"     # Solo per gli endpoint di auth
    )

def clear_auth_cookies(response: Response):
    """Rimuove i cookie di autenticazione"""
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/auth")

# ================================
# DEPENDENCY MODIFICATO
# ================================

async def get_current_user_from_cookie(request: Request):
    """Recupera l'utente dal cookie httpOnly"""
    access_token = request.cookies.get("access_token")
    
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token di accesso mancante"
        )
    
    try:
        payload = jwt.decode(access_token, settings.JWT_SECRET_KEY, algorithms=['HS256'])
        user_id = payload.get("user_id")
        token_type = payload.get("type")
        
        if not user_id or token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token non valido"
            )
        
        # Recupera i dati dell'utente dal database
        user_response = supabase_client.table("users").select("*").eq("id", user_id).execute()
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Utente non trovato"
            )
        
        return user_response.data[0]
        
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token non valido"
        )

# ================================
# ENDPOINT MODIFICATI
# ================================
@router.get("/google/url", response_model=GoogleAuthUrlResponse)
async def get_google_auth_url(request: Request):
    """Genera URL per Google OAuth"""
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
        raise HTTPException(status_code=500, detail=f"Errore generando URL Google: {str(e)}")

@router.post("/google/token", response_model=AuthResponse)
async def google_token_login(token_request: GoogleTokenRequest):
    """Login diretto tramite ID token Google"""
    try:
        idinfo = id_token.verify_oauth2_token(token_request.token, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
        email = idinfo.get("email")
        google_id = idinfo.get("sub")
        name = idinfo.get("name", "")
        picture = idinfo.get("picture", "")

        if not email or not google_id:
            raise HTTPException(status_code=400, detail="Token Google non valido")

        user_response = supabase_client.table("users").select("*").eq("email", email).execute()
        if user_response.data:
            user_data = user_response.data[0]
            supabase_client.table("users").update({"updated_at": datetime.utcnow().isoformat()}).eq("id", user_data["id"]).execute()
        else:
            new_user = {
                "email": email,
                "full_name": name,
                "avatar_url": picture,
                "google_id": google_id,
                "subscription_tier": "free",
                "credits_remaining": 100
            }
            result = supabase_client.table("users").insert(new_user).execute()
            if not result.data:
                raise HTTPException(status_code=500, detail="Errore creando utente Google")
            user_data = result.data[0]

        access_token = create_access_token({"sub": email, "user_id": user_data["id"]})
        return AuthResponse(user=UserResponse(**user_data), access_token=access_token, token_type="bearer", expires_in=3600)
    except ValueError:
        raise HTTPException(status_code=400, detail="Token Google non valido")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore autenticazione: {str(e)}")

@router.post("/google/callback")
async def google_callback(request: Request):
    """Gestisce callback da Google OAuth con cookie"""
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
                details="Authorization code mancante"
            )
            raise HTTPException(status_code=400, detail="Authorization code mancante")

        # Exchange code per token
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{settings.FRONTEND_URL}/auth/callback"
            }
        )
        token_response.raise_for_status()
        tokens = token_response.json()

        id_token_jwt = tokens.get("id_token")
        if not id_token_jwt:
            raise HTTPException(status_code=400, detail="ID token mancante")

        idinfo = id_token.verify_oauth2_token(id_token_jwt, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
        email = idinfo.get("email")
        google_id = idinfo.get("sub")
        name = idinfo.get("name", "")
        picture = idinfo.get("picture", "")

        if not email or not google_id:
            raise HTTPException(status_code=400, detail="Email o Google ID mancanti")

        # Controlla se esiste utente
        user_response = supabase_client.table("users").select("*").eq("email", email).execute()
        if user_response.data:
            user_data = user_response.data[0]
            user_id = user_data["id"]
            
            # Aggiorna con timestamp corretto
            update_data = {"updated_at": datetime.utcnow().isoformat()}
            supabase_client.table("users").update(update_data).eq("id", user_id).execute()
            
            action = "google_login_existing_user"
        else:
            user_id = str(uuid.uuid4())
            current_time = datetime.utcnow().isoformat()
            
            new_user = {
                "id": user_id,
                "email": email,
                "full_name": name,
                "avatar_url": picture,
                "subscription_tier": "free",
                "credits_remaining": 100,
                "google_id": google_id,
                "created_at": current_time,
                "updated_at": current_time,
                "password_hash": None  # Utente Google non ha password
            }
            
            result = supabase_client.table("users").insert(new_user).execute()
            if not result.data:
                raise HTTPException(status_code=500, detail="Errore creando nuovo utente")
            user_data = result.data[0]
            action = "google_signup_new_user"

        # Serializza i campi datetime prima di usare UserResponse
        user_data_clean = serialize_datetime_fields(user_data)
        user_data_clean.pop("password_hash", None)
        
        # Crea i token
        access_token = create_access_token({"sub": email, "user_id": user_data["id"]})
        refresh_token = create_refresh_token({"sub": email, "user_id": user_data["id"]})
        
        # Crea la risposta JSON senza token
        response_data = {
            "user": user_data_clean,  # Usa i dati già serializzati
            "message": "Autenticazione Google completata con successo"
        }
        
        # Crea la risposta e imposta i cookie
        response = JSONResponse(content=response_data)
        set_auth_cookies(response, access_token, refresh_token)
        
        # Logging
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            additional_data={"action": action, "email": email, "authentication_method": "google_oauth"}
        )
        
        return response
        
    except requests.RequestException as e:
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            error=f"Google API error: {str(e)}"
        )
        raise HTTPException(status_code=400, detail=f"Google API error: {str(e)}")
    except Exception as e:
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Errore autenticazione: {str(e)}")

@router.post("/login")
async def login_user(login_data: UserLoginRequest, request: Request):
    """Login con cookie httpOnly"""
    start_time = time.time()
    user_id = None
    
    try:
        user_result = supabase_client.table("users").select("*").eq("email", login_data.email).execute()
        if not user_result.data:
            await log_security_event(
                supabase_client=supabase_client,
                event="login_failure_user_not_found",
                client_ip=api_logger._get_client_ip(request),
                details=f"Email: {login_data.email}"
            )
            raise HTTPException(status_code=401, detail="Email o password non corretti")
        
        user_record = user_result.data[0]
        user_id = user_record["id"]
        
        if not user_record.get("password_hash"):
            await log_security_event(
                supabase_client=supabase_client,
                event="login_failure_google_user",
                client_ip=api_logger._get_client_ip(request),
                details=f"Email: {login_data.email}",
                user_id=user_id
            )
            raise HTTPException(status_code=401, detail="Questo account utilizza Google OAuth. Usa il login con Google.")
        
        if not verify_password(login_data.password, user_record["password_hash"]):
            await log_security_event(
                supabase_client=supabase_client,
                event="login_failure_wrong_password",
                client_ip=api_logger._get_client_ip(request),
                details=f"Email: {login_data.email}",
                user_id=user_id
            )
            raise HTTPException(status_code=401, detail="Email o password non corretti")

        # Aggiorna last login
        supabase_client.table("users").update({"updated_at": datetime.utcnow().isoformat()}).eq("id", user_id).execute()
        
        # Crea i token
        access_token = create_access_token({"sub": user_record["email"], "user_id": user_id})
        refresh_token = create_refresh_token({"sub": user_record["email"], "user_id": user_id})
        
        # Rimuovi dati sensibili
        user_record.pop("password_hash", None)
        
        # Crea risposta senza token
        response_data = {
            "user": UserResponse(**user_record).dict(),
            "message": "Login completato con successo"
        }
        
        response = JSONResponse(content=response_data)
        set_auth_cookies(response, access_token, refresh_token)
        
        # Logging
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            additional_data={"action": "user_login", "email": login_data.email}
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")

@router.post("/register")
async def register_user(user_data: UserRegisterRequest, request: Request):
    """Registrazione con cookie httpOnly"""
    start_time = time.time()
    user_id = None
    
    try:
        existing_user = supabase_client.table("users").select("email").eq("email", user_data.email).execute()
        if existing_user.data:
            await log_security_event(
                supabase_client=supabase_client,
                event="registration_attempt_existing_email",
                client_ip=api_logger._get_client_ip(request),
                details=f"Email: {user_data.email}"
            )
            raise HTTPException(status_code=400, detail="Utente già esistente")

        hashed_password = hash_password(user_data.password)
        user_id = str(uuid.uuid4())
        new_user = {
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
        
        result = supabase_client.table("users").insert(new_user).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Errore creando utente")
        
        user_record = result.data[0]
        user_record.pop("password_hash", None)
        
        # Crea i token
        access_token = create_access_token({"sub": user_record["email"], "user_id": user_record["id"]})
        refresh_token = create_refresh_token({"sub": user_record["email"], "user_id": user_record["id"]})
        
        # Crea risposta senza token
        response_data = {
            "user": UserResponse(**user_record).dict(),
            "message": "Registrazione completata con successo"
        }
        
        response = JSONResponse(content=response_data)
        set_auth_cookies(response, access_token, refresh_token)
        
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            additional_data={"action": "user_registration", "email": user_data.email}
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")

@router.post("/refresh")
async def refresh_token(request: Request):
    """Rinnova l'access token usando il refresh token"""
    refresh_token = request.cookies.get("refresh_token")
    
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token mancante"
        )
    
    try:
        payload = jwt.decode(refresh_token, settings.JWT_SECRET_KEY, algorithms=['HS256'])
        user_id = payload.get("user_id")
        email = payload.get("sub")
        token_type = payload.get("type")
        
        if not user_id or not email or token_type != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token non valido"
            )
        
        # Verifica che l'utente esista ancora
        user_response = supabase_client.table("users").select("*").eq("id", user_id).execute()
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Utente non trovato"
            )
        
        user_data = user_response.data[0]
        
        # Crea nuovo access token
        new_access_token = create_access_token({"sub": email, "user_id": user_id})
        
        # Risposta con dati utente aggiornati
        user_data.pop("password_hash", None)
        response_data = {
            "user": UserResponse(**user_data).dict(),
            "message": "Token rinnovato con successo"
        }
        
        response = JSONResponse(content=response_data)
        response.set_cookie(
            key="access_token",
            value=new_access_token,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=900,
            path="/"
        )
        
        return response
        
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token non valido"
        )

@router.post("/logout")
async def logout(request: Request):
    """Logout che rimuove i cookie"""
    response = JSONResponse(content={"message": "Logout completato con successo"})
    clear_auth_cookies(response)
    return response

@router.get("/me")
async def get_current_user_data(current_user: dict = Depends(get_current_user_from_cookie)):
    """Restituisce i dati dell'utente autenticato dai cookie"""
    user_record = current_user.copy()
    user_record.pop("password_hash", None)
    return UserResponse(**user_record)