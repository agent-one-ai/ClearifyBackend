from fastapi import APIRouter, HTTPException, Request, Depends, status, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import requests
from datetime import datetime, timedelta, timezone
import uuid
import os
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

from app.services import email_service

router = APIRouter()
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
api_logger = SupabaseAPILogger(supabase_client)

# ================================
# UTILITY FUNCTIONS CORRETTE PER UTC
# ================================

def get_utc_now() -> str:
    """Restituisce un timestamp UTC correttamente formattato per Supabase"""
    return datetime.now(timezone.utc).isoformat()

def get_utc_datetime() -> datetime:
    """Restituisce un datetime UTC per calcoli interni"""
    return datetime.now(timezone.utc)

def serialize_datetime_fields(data: dict) -> dict:
    """Converte tutti i campi datetime in stringhe ISO con timezone UTC"""
    result = data.copy()
    for key, value in result.items():
        if isinstance(value, datetime):
            # Assicurati che sia in UTC e aggiungi il timezone
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            result[key] = value.isoformat()
    return result

def get_cookie_settings():
    """Configurazione cookie dinamica per HTTPS"""
    is_development = os.getenv("ENVIRONMENT", "development") == "development"
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    is_https = frontend_url.startswith("https://")
    
    if is_development:
        # Configurazione per sviluppo HTTPS
        return {
            "httponly": True,
            "secure": is_https,        # True se frontend è HTTPS
            "samesite": "lax",         # "lax" per sviluppo cross-origin
            "domain": None,            # None per localhost
            "path": "/"
        }
    else:
        # Configurazione per produzione
        return {
            "httponly": True,
            "secure": True,            # Sempre True in produzione
            "samesite": "strict",      # "strict" in produzione
            "domain": os.getenv("COOKIE_DOMAIN"),
            "path": "/"
        }

def debug_request_info(request: Request):
    """Debug function per HTTPS troubleshooting"""
    if os.getenv("DEBUG", "false").lower() == "true":
        print(f"🌐 {request.method} {request.url}")
        print(f"🔗 Origin: {request.headers.get('origin', 'None')}")
        print(f"🔗 Referer: {request.headers.get('referer', 'None')}")
        print(f"🍪 Request cookies: {dict(request.cookies)}")
        print(f"🔐 User-Agent: {request.headers.get('user-agent', 'Unknown')[:50]}...")
        print(f"⚙️ Frontend URL: {os.getenv('FRONTEND_URL')}")

def create_access_token(data: dict, expires_delta: int = 900):  # 15 minuti
    """Token di accesso di breve durata"""
    to_encode = data.copy()
    expire = get_utc_datetime() + timedelta(seconds=expires_delta)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm='HS256')
    return encoded_jwt

def create_refresh_token(data: dict, expires_delta: int = 604800):  # 7 giorni
    """Token di refresh di lunga durata"""
    to_encode = data.copy()
    expire = get_utc_datetime() + timedelta(seconds=expires_delta)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm='HS256')
    return encoded_jwt

def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    """Imposta i cookie httpOnly con configurazione HTTPS dinamica"""
    
    cookie_settings = get_cookie_settings()
    
    # Access token - 15 minuti
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=900,  # 15 minuti
        expires=get_utc_datetime() + timedelta(minutes=15),
        **cookie_settings
    )
    
    # Refresh token - 7 giorni
    response.set_cookie(
        key="refresh_token", 
        value=refresh_token,
        max_age=604800,  # 7 giorni
        expires=get_utc_datetime() + timedelta(days=7),
        **cookie_settings
    )
    
    # Debug logging
    if os.getenv("DEBUG", "false").lower() == "true":
        print(f"🍪 Setting cookies with config: {cookie_settings}")
        print(f"🍪 Access token length: {len(access_token)}")
        print(f"🍪 Refresh token length: {len(refresh_token)}")

def clear_auth_cookies(response: Response):
    """Rimuove i cookie di autenticazione con configurazione HTTPS"""
    
    cookie_settings = get_cookie_settings()
    # Rimuovi httponly per delete_cookie
    cookie_settings_for_delete = {k: v for k, v in cookie_settings.items() if k != 'httponly'}
    
    response.delete_cookie(
        key="access_token",
        **cookie_settings_for_delete
    )
    response.delete_cookie(
        key="refresh_token",
        **cookie_settings_for_delete
    )
    
    if os.getenv("DEBUG", "false").lower() == "true":
        print(f"🍪 Clearing cookies with config: {cookie_settings_for_delete}")

def hash_password(password: str) -> str:
    """Hash della password"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica password"""
    return pwd_context.verify(plain_password, hashed_password)

# ================================
# DEPENDENCY AGGIORNATO CON DEBUG
# ================================

async def get_current_user_from_cookie(request: Request):
    """Recupera l'utente dal cookie httpOnly con debug HTTPS"""
    
    # Debug per sviluppo
    debug_request_info(request)
    
    access_token = request.cookies.get("access_token")
    
    if not access_token:
        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"❌ No access_token cookie found. Available cookies: {list(request.cookies.keys())}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token di accesso mancante"
        )
    
    try:
        payload = jwt.decode(access_token, settings.JWT_SECRET_KEY, algorithms=['HS256'])
        user_id = payload.get("user_id")
        token_type = payload.get("type")
        
        if not user_id or token_type != "access":
            if os.getenv("DEBUG", "false").lower() == "true":
                print(f"❌ Invalid token payload: user_id={user_id}, type={token_type}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token non valido"
            )
        
        # Recupera i dati dell'utente dal database
        user_response = supabase_client.table("users").select("*").eq("id", user_id).execute()
        if not user_response.data:
            if os.getenv("DEBUG", "false").lower() == "true":
                print(f"❌ User not found in database: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Utente non trovato"
            )
        
        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"✅ User authenticated successfully: {user_response.data[0].get('email')}")
        
        return user_response.data[0]
        
    except JWTError as e:
        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"❌ JWT decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token non valido"
        )

# ================================
# ENDPOINT CORRETTI CON UTC
# ================================

@router.get("/google/url", response_model=GoogleAuthUrlResponse)
async def get_google_auth_url(request: Request):
    """Genera URL per Google OAuth con redirect HTTPS"""
    start_time = time.time()
    
    debug_request_info(request)
    
    try:
        # Usa FRONTEND_URL dall'environment (dovrebbe essere https://localhost:3000)
        redirect_uri = f"{settings.FRONTEND_URL}/auth/callback"
        
        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={settings.GOOGLE_CLIENT_ID}&"
            f"redirect_uri={redirect_uri}&"
            "response_type=code&"
            "scope=openid email profile&"
            "access_type=offline&"
            "prompt=consent"
        )
        
        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"🔗 Generated Google auth URL with redirect: {redirect_uri}")
        
        response = GoogleAuthUrlResponse(auth_url=auth_url)
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            additional_data={"action": "google_auth_url_generated", "redirect_uri": redirect_uri}
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

@router.post("/google/callback")
async def google_callback(request: Request):
    """Gestisce callback da Google OAuth con cookie HTTPS"""
    start_time = time.time()
    user_id = None
    
    debug_request_info(request)
    
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

        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"🔑 Processing Google callback with code: {code[:20]}...")

        # Exchange code per token con redirect URI HTTPS
        redirect_uri = f"{settings.FRONTEND_URL}/auth/callback"
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri
            }
        )
        token_response.raise_for_status()
        tokens = token_response.json()

        id_token_jwt = tokens.get("id_token")
        if not id_token_jwt:
            raise HTTPException(status_code=400, detail="ID token mancante")

        idinfo = id_token.verify_oauth2_token(
                    id_token_jwt, 
                    google_requests.Request(), 
                    settings.GOOGLE_CLIENT_ID,
                    clock_skew_in_seconds=10
                )
        email = idinfo.get("email")
        google_id = idinfo.get("sub")
        name = idinfo.get("name", "")
        picture = idinfo.get("picture", "")

        if not email or not google_id:
            raise HTTPException(status_code=400, detail="Email o Google ID mancanti")

        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"👤 Google user info: {email}, {name}")

        # Controlla se esiste utente
        user_response = supabase_client.table("users").select("*").eq("email", email).execute()
        if user_response.data:
            user_data = user_response.data[0]
            user_id = user_data["id"]
            
            # Aggiorna timestamp con UTC corretto
            update_data = {"updated_at": get_utc_now()}
            supabase_client.table("users").update(update_data).eq("id", user_id).execute()
            
            action = "google_login_existing_user"
        else:
            user_id = str(uuid.uuid4())
            current_time = get_utc_now()
            
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
                "password_hash": None
            }
            
            result = supabase_client.table("users").insert(new_user).execute()
            if not result.data:
                raise HTTPException(status_code=500, detail="Errore creando nuovo utente")
            
            #Vado a mandare direttamente l'email di benvenuto, senza creare un task
            email_service.send_registration_confirmation_email(
                to_email=email,
                customer_name=name
            )

            user_data = result.data[0]
            action = "google_signup_new_user"

        # Serializza i campi datetime
        user_data_clean = serialize_datetime_fields(user_data)
        user_data_clean.pop("password_hash", None)
        
        # Crea i token
        access_token = create_access_token({"sub": email, "user_id": user_data["id"]})
        refresh_token = create_refresh_token({"sub": email, "user_id": user_data["id"]})
        
        # Crea la risposta JSON
        response_data = {
            "user": user_data_clean,
            "message": "Autenticazione Google completata con successo"
        }
        
        # Crea la risposta e imposta i cookie HTTPS
        response = JSONResponse(content=response_data)
        set_auth_cookies(response, access_token, refresh_token)
        
        # Logging
        process_time = (time.time() - start_time) * 1000
        await api_logger.log_api_call(
            request=request,
            response_time=process_time,
            user_id=user_id,
            additional_data={
                "action": action, 
                "email": email, 
                "authentication_method": "google_oauth",
                "https_enabled": settings.FRONTEND_URL.startswith("https://")
            }
        )
        
        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"✅ Google authentication successful for {email}")
        
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
    """Login con cookie httpOnly HTTPS - CORRETTO"""
    start_time = time.time()
    user_id = None
    
    debug_request_info(request)
    
    try:
        print(f"DEBUG: Starting login for {login_data.email}")
        
        # Trova utente
        user_result = supabase_client.table("users").select("*").eq("email", login_data.email).execute()
        if not user_result.data:
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="login_fail",  # Accorciato
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {login_data.email}"
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
                
            raise HTTPException(status_code=401, detail="Email o password non corretti")
        
        user_record = user_result.data[0]
        user_id = user_record["id"]
        
        print(f"DEBUG: User found: {user_record['email']}")
        
        # Verifica che abbia password (non sia account Google)
        if not user_record.get("password_hash"):
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="google_acc",  # Accorciato
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {login_data.email}",
                    user_id=user_id
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
                
            raise HTTPException(status_code=401, detail="Questo account utilizza Google OAuth. Usa il login con Google.")
        
        print(f"DEBUG: Verifying password")
        if not verify_password(login_data.password, user_record["password_hash"]):
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="wrong_pwd",  # Accorciato
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {login_data.email}",
                    user_id=user_id
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
                
            raise HTTPException(status_code=401, detail="Email o password non corretti")

        print(f"DEBUG: Password verified, updating user")
        # Aggiorna last login con UTC corretto
        supabase_client.table("users").update({"updated_at": get_utc_now()}).eq("id", user_id).execute()
        
        print(f"DEBUG: Creating tokens")
        # Crea token
        access_token = create_access_token({"sub": user_record["email"], "user_id": user_id})
        refresh_token = create_refresh_token({"sub": user_record["email"], "user_id": user_id})
        
        # Prepara dati utente - SERIALIZZA DATETIME
        user_record_clean = user_record.copy()
        user_record_clean.pop("password_hash", None)
        user_record_serialized = serialize_datetime_fields(user_record_clean)
        
        print(f"DEBUG: Creating response")
        # Crea risposta con dati serializzati
        response_data = {
            "user": user_record_serialized,  # Usa dati serializzati invece di UserResponse().dict()
            "message": "Login completato con successo"
        }
        
        response = JSONResponse(content=response_data)
        set_auth_cookies(response, access_token, refresh_token)
        
        # Logging con gestione errori
        try:
            print(f"DEBUG: Logging API call")
            process_time = (time.time() - start_time) * 1000
            await api_logger.log_api_call(
                request=request,
                response_time=process_time,
                user_id=user_id,
                additional_data={
                    "action": "login",  # Accorciato
                    "email": login_data.email[:50]  # Limita lunghezza
                }
            )
            print(f"DEBUG: API call logged successfully")
        except Exception as log_error:
            print(f"WARNING: Failed to log login: {str(log_error)}")
        
        print(f"DEBUG: Login completed successfully for {login_data.email}")
        return response
        
    except HTTPException:
        # Re-raise HTTPException senza modifiche
        raise
    except Exception as e:
        print(f"ERROR: Login failed for {login_data.email}: {str(e)}")
        print(f"ERROR: Exception type: {type(e).__name__}")
        
        # Logging sicuro per errori
        try:
            process_time = (time.time() - start_time) * 1000
            await api_logger.log_api_call(
                request=request,
                response_time=process_time,
                user_id=user_id,
                error=str(e)[:200]  # Tronca errore lungo
            )
        except Exception as log_error:
            print(f"WARNING: Failed to log error: {str(log_error)}")
            
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")

@router.post("/register")
async def register_user(user_data: UserRegisterRequest, request: Request):
    """Registrazione con cookie httpOnly HTTPS - CORRETTO"""
    start_time = time.time()
    user_id = None
    
    debug_request_info(request)
    
    try:
        print(f"DEBUG: Starting registration for {user_data.email}")
        
        # Controlla se utente esiste già
        existing_user = supabase_client.table("users").select("email").eq("email", user_data.email).execute()
        if existing_user.data:
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="reg_exist",  # Accorciato per evitare limite caratteri
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {user_data.email}"
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
            
            raise HTTPException(status_code=400, detail="Utente già esistente")

        print(f"DEBUG: Hashing password for {user_data.email}")
        hashed_password = hash_password(user_data.password)
        user_id = str(uuid.uuid4())
        current_time = get_utc_now()
        
        print(f"DEBUG: Creating user record for {user_data.email}")
        new_user = {
            "id": user_id,
            "email": user_data.email,
            "full_name": f"{user_data.firstName} {user_data.lastName}",
            "password_hash": hashed_password,
            "subscription_tier": "free",
            "credits_remaining": 100,
            "avatar_url": None,
            "created_at": current_time,
            "updated_at": current_time,
            "google_id": None
        }
        
        print(f"DEBUG: Inserting user into database")
        result = supabase_client.table("users").insert(new_user).execute()
        if not result.data:
            raise HTTPException(status_code=500, detail="Errore creando utente")
        
        user_record = result.data[0]
        print(f"DEBUG: User created successfully: {user_record['id']}")
        
        # Rimuovi password hash e serializza datetime
        user_record_clean = user_record.copy()
        user_record_clean.pop("password_hash", None)
        user_record_serialized = serialize_datetime_fields(user_record_clean)
        
        print(f"DEBUG: Creating JWT tokens")
        access_token = create_access_token({"sub": user_record["email"], "user_id": user_record["id"]})
        refresh_token = create_refresh_token({"sub": user_record["email"], "user_id": user_record["id"]})
        
        print(f"DEBUG: Preparing JSON response")
        response_data = {
            "user": user_record_serialized,  # Usa dati serializzati invece di UserResponse
            "message": "Registrazione completata con successo"
        }
        
        print(f"DEBUG: Creating JSONResponse")
        response = JSONResponse(content=response_data)
        
        print(f"DEBUG: Setting auth cookies")
        set_auth_cookies(response, access_token, refresh_token)
        
        # Log API call con gestione errori migliorata
        try:
            print(f"DEBUG: Logging API call")
            process_time = (time.time() - start_time) * 1000
            await api_logger.log_api_call(
                request=request,
                response_time=process_time,
                user_id=user_id,
                additional_data={
                    "action": "register",  # Accorciato per evitare limite
                    "email": user_data.email[:50]  # Limita lunghezza email
                }
            )
            print(f"DEBUG: API call logged successfully")
        except Exception as log_error:
            print(f"WARNING: Failed to log API call: {str(log_error)}")
            # Non far fallire la registrazione per un errore di logging
        
        print(f"DEBUG: Registration completed successfully for {user_data.email}")
        return response
        
    except HTTPException:
        # Re-raise HTTPException senza modifiche
        raise
    except Exception as e:
        print(f"ERROR: Registration failed for {user_data.email}: {str(e)}")
        print(f"ERROR: Exception type: {type(e).__name__}")
        
        # Log errore con gestione sicura
        try:
            process_time = (time.time() - start_time) * 1000
            await api_logger.log_api_call(
                request=request,
                response_time=process_time,
                user_id=user_id,
                error=str(e)[:200]  # Tronca errore lungo
            )
        except Exception as log_error:
            print(f"WARNING: Failed to log error: {str(log_error)}")
            
        raise HTTPException(status_code=500, detail=f"Errore interno: {str(e)}")

@router.post("/refresh")
async def refresh_token_endpoint(request: Request):
    """Rinnova l'access token usando il refresh token HTTPS"""
    
    debug_request_info(request)
    
    refresh_token = request.cookies.get("refresh_token")
    
    if not refresh_token:
        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"❌ No refresh_token cookie found. Available cookies: {list(request.cookies.keys())}")
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
        
        # Imposta solo il nuovo access token (refresh token rimane valido)
        cookie_settings = get_cookie_settings()
        response.set_cookie(
            key="access_token",
            value=new_access_token,
            max_age=900,
            expires=get_utc_datetime() + timedelta(minutes=15),
            **cookie_settings
        )
        
        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"✅ Token refreshed for user: {email}")
        
        return response
        
    except JWTError as e:
        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"❌ JWT refresh error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token non valido"
        )

@router.post("/logout")
async def logout(request: Request):
    """Logout che rimuove i cookie HTTPS"""
    
    debug_request_info(request)
    
    response = JSONResponse(content={"message": "Logout completato con successo"})
    clear_auth_cookies(response)
    
    if os.getenv("DEBUG", "false").lower() == "true":
        print(f"✅ Logout completed, cookies cleared")
    
    return response

@router.get("/me")
async def get_current_user_data(
    request: Request,
    current_user: dict = Depends(get_current_user_from_cookie)
):
    """Restituisce i dati dell'utente autenticato dai cookie HTTPS"""
    
    user_record = current_user.copy()
    user_record.pop("password_hash", None)
    
    if os.getenv("DEBUG", "false").lower() == "true":
        print(f"✅ User data retrieved for: {user_record.get('email')}")
    
    return UserResponse(**user_record)

# Endpoint legacy per compatibilità
@router.post("/google/token", response_model=AuthResponse)
async def google_token_login(token_request: GoogleTokenRequest):
    """Login diretto tramite ID token Google (legacy)"""
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
            supabase_client.table("users").update({"updated_at": get_utc_now()}).eq("id", user_data["id"]).execute()
        else:
            current_time = get_utc_now()
            new_user = {
                "email": email,
                "full_name": name,
                "avatar_url": picture,
                "google_id": google_id,
                "subscription_tier": "free",
                "credits_remaining": 100,
                "created_at": current_time,
                "updated_at": current_time
            }
            result = supabase_client.table("users").insert(new_user).execute()
            if not result.data:
                raise HTTPException(status_code=500, detail="Errore creando utente Google")
            user_data = result.data[0]

        access_token = create_access_token({"sub": email, "user_id": user_data["id"]})
        return AuthResponse(user=UserResponse(**user_data), access_token=access_token, token_type="bearer", expires_in=900)
    except ValueError:
        raise HTTPException(status_code=400, detail="Token Google non valido")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore autenticazione: {str(e)}")