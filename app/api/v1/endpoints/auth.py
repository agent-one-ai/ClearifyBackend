from fastapi import APIRouter, HTTPException, Request, Depends, status, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from pyasn1.type.univ import Null
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
    VerificationEmailRequestRequest,
    GoogleAuthUrlResponse,
    UserRegisterRequest,
    UserLoginRequest,
    VerificationTokenRequest
)
from app.core.logging import SupabaseAPILogger, log_request, log_security_event
from app.workers.tasks import send_verification_email_task
import time
import uuid

from app.services import email_service

router = APIRouter()
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
api_logger = SupabaseAPILogger(supabase_client)

# ================================
# UTILITY FUNCTIONS
# ================================

def get_utc_now() -> str:
    """Restituisce un timestamp UTC correttamente formattato per Supabase"""
    return datetime.now(timezone.utc).isoformat()

def get_utc_datetime() -> datetime:
    """Restituisce un datetime UTC per calcoli interni"""
    return datetime.now(timezone.utc)

def get_verification_token() -> str:
    return str(uuid.uuid4())

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

def create_access_token(data: dict, expires_delta: int = 604800):  # 7 giorni
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
        max_age=604800,  # 7 giorni
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
        return response
    except Exception as e:
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
            
            # Aggiorno timestamp e nel dubbio metto sempre che è verificato, con Google è sempre corretto
            update_data = {"updated_at": get_utc_now(), "isVerified": True}
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
                "password_hash": None,
                "isVerified": True
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
        
        if os.getenv("DEBUG", "false").lower() == "true":
            print(f"✅ Google authentication successful for {email}")
        
        return response
        
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Google API error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore autenticazione: {str(e)}")

#Creo un endpoint che accoda una task per mandare email di verifica esistenza
@router.post("/verifyEmail")
async def verifyUserEmail(verification_data: VerificationEmailRequestRequest, request: Request):
    """Metodo per inviare email di conferma account"""
    
    debug_request_info(request)
    
    try:
        if not verification_data.email:
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="verification_fail",
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {verification_data.email}"
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
                
            raise HTTPException(
                status_code=401, 
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Email non corretta"
                }
            )   

        # Trova utente
        user_result = supabase_client.table("users").select("*").eq("email", verification_data.email).execute()

        if not user_result.data:
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="login_fail",
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {verification_data.email}"
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
                
            raise HTTPException(
                status_code=401, 
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Email non corretta"
                }
            )
        
        user_record = user_result.data[0]
        user_token = user_record["verification_token"]
        
        # Verifico che il token ci sia, se cosi non fosse, ne genero uno ora
        if not user_token:
            user_token = get_verification_token()

            update_data = {"verification_token": user_token}

            #Lo salvo su database e refresho
            result = (
                        supabase_client
                        .table("users")
                        .update(update_data)
                        .eq("email", user_record["email"])
                        .execute()
                    )

            #Rifaccio il get per refreshare il token direttamente in user_result
            user_result = supabase_client.table("users").select("*").eq("email", verification_data.email).execute()

        #Una volta trovato o generato il token, posso procedere con l'invio della email  
        email_task = send_verification_email_task.apply_async(
            kwargs={
                'email_data': {
                    'to_email': verification_data.email,
                    'username': user_record.get("full_name") if user_record.get("full_name") else verification_data.email,
                    'verificationToken': user_token,
                }
            },
            queue="emails",
            priority=6,
            retry=True,
            retry_policy={
                'max_retries': 3,
                'interval_start': 60,
                'interval_step': 60,
                'interval_max': 300
            }
        )

        response_data = {
            "success": True
        }
        
        response = JSONResponse(content=response_data)
        
        print(f"DEBUG: Email verification completed successfully for {verification_data.email}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: Login failed for {verification_data.email}: {str(e)}")
        print(f"ERROR: Exception type: {type(e).__name__}")

#Creo un endpoint che verifichi se il token corrisponde a quello generato e verifica la mail
@router.post("/verifyToken")
async def verifyUserEmail(verification_data: VerificationTokenRequest, request: Request):
    """Metodo per verificare il token"""

    try:
        if not verification_data.email:
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="verification_fail",
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email not found"
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
                
            raise HTTPException(
                status_code=401, 
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Email non corretta"
                }
            )   

        # Trova utente
        user_result = supabase_client.table("users").select("*").eq("email", verification_data.email).execute()

        if not user_result.data:
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="login_fail",
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {verification_data.email}"
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
                
            raise HTTPException(
                status_code=401, 
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Email non corretta"
                }
            )
        
        user_record = user_result.data[0]
        user_token = user_record["verification_token"]
        
        # Verifico che il token ci sia, se cosi non fosse, ne genero uno ora
        if not user_token:
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="login_fail",
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {verification_data.email}"
                )
            except Exception as log_error:
                print(f"WARNING: Token not found: {str(log_error)}")
                
            raise HTTPException(
                status_code=401, 
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Token non trovato"
                }
            )

        #Una volta trovato o generato il token, controllo che sia uguale a quello passato al metodo
        if user_token == verification_data.token:
            update_data = {"isVerified": True}

            #Salvo su db la verifica e ritorno
            result = (
                        supabase_client
                        .table("users")
                        .update(update_data)
                        .eq("email", user_record["email"])
                        .execute()
                    )

            # Invio email di benvenuto dopo la verifica
            email_service.send_registration_confirmation_email(
                to_email=user_record["email"],
                customer_name=user_record.get("full_name") if user_record.get("full_name") else user_record["email"]
            )

            response_data = {
                "success": True
            }
        else:
            raise HTTPException(
                status_code=401, 
                detail={
                    "code": "INVALID_TOKEN",
                    "message": "Token non valido"
                }
            )

            response_data = {
                "success": False
            }
        
        response = JSONResponse(content=response_data)
        
        print(f"DEBUG: Token verified successfully for {verification_data.email}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: Exception type: {type(e).__name__}")

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
                    event="login_fail",
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {login_data.email}"
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
                
            raise HTTPException(
                status_code=401, 
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Email o password non corretti"
                }
            )
        
        user_record = user_result.data[0]
        user_id = user_record["id"]
        
        print(f"DEBUG: User found: {user_record['email']}")
        
        # Verifica che abbia password (non sia account Google)
        if not user_record.get("password_hash"):
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="google_acc",
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {login_data.email}",
                    user_id=user_id
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
                
            raise HTTPException(
                status_code=401, 
                detail={
                    "code": "GOOGLE_ACCOUNT",
                    "message": "Questo account utilizza Google OAuth. Usa il login con Google."
                }
            )
        
        print(f"DEBUG: Verifying password")
        if not verify_password(login_data.password, user_record["password_hash"]):
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="wrong_pwd",
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {login_data.email}",
                    user_id=user_id
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
                
            raise HTTPException(
                status_code=401, 
                detail={
                    "code": "INVALID_CREDENTIALS",
                    "message": "Email o password non corretti"
                }
            )

        #Se l'utente non è verificato, metto in coda la mail di verifica e devo ritornare al front end l'errore
        if user_record["isVerified"] == False:
            token = Null

            #Se il token per un qualche motivo non risulta creato precedentemente in fase di registrazione, lo creo ora
            if not user_record["verification_token"]:
                #Ottengo un nuovo token e lo salvo su database
                token = get_verification_token()

                update_data = {"verification_token": token}

                #Lo salvo su database e refresho
                result = (
                            supabase_client
                            .table("users")
                            .update(update_data)
                            .eq("email", user_record["email"])
                            .execute()
                        )

                #Rifaccio il get per refreshare il token direttamente in user_result
                user_record = supabase_client.table("users").select("*").eq("email", login_data.email).execute()


            email_task = send_verification_email_task.apply_async(
                kwargs={
                    'email_data': {
                        'to_email': login_data.email,
                        'username': user_record.get("full_name") if user_record.get("full_name") else login_data.email,
                        'verificationToken': user_record.get("verification_token"),
                    }
                },
                queue="emails",
                priority=6,
                retry=True,
                retry_policy={
                    'max_retries': 3,
                    'interval_start': 60,
                    'interval_step': 60,
                    'interval_max': 300
                }
            )

        print(f"DEBUG: Password verified, updating user")
        supabase_client.table("users").update({"updated_at": get_utc_now()}).eq("id", user_id).execute()
        
        print(f"DEBUG: Creating tokens")
        access_token = create_access_token({"sub": user_record["email"], "user_id": user_id})
        refresh_token = create_refresh_token({"sub": user_record["email"], "user_id": user_id})
        
        user_record_clean = user_record.copy()
        user_record_clean.pop("password_hash", None)
        user_record_serialized = serialize_datetime_fields(user_record_clean)
        
        print(f"DEBUG: Creating response")
        response_data = {
            "user": user_record_serialized,
            "message": "Login completato con successo"
        }
        
        response = JSONResponse(content=response_data)
        set_auth_cookies(response, access_token, refresh_token)
        
        try:
            print(f"DEBUG: Logging API call")
            print(f"DEBUG: API call logged successfully")
        except Exception as log_error:
            print(f"WARNING: Failed to log login: {str(log_error)}")
        
        print(f"DEBUG: Login completed successfully for {login_data.email}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: Login failed for {login_data.email}: {str(e)}")
        print(f"ERROR: Exception type: {type(e).__name__}")
    
        raise HTTPException(
            status_code=500, 
            detail={
                "code": "INTERNAL_ERROR",
                "message": f"Errore interno del server"
            }
        )

@router.post("/register")
async def register_user(user_data: UserRegisterRequest, request: Request):
    """Registrazione con cookie httpOnly HTTPS"""
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
                    event="reg_exist",
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {user_data.email}"
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")
            
            raise HTTPException(
                status_code=409,  # 409 Conflict
                detail={
                    "code": "EMAIL_EXISTS",
                    "message": "This email is already registered"
                }
            )

        # Validazione password
        if len(user_data.password) < 8:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "WEAK_PASSWORD",
                    "message": "Password must be at least 8 characters long"
                }
            )

        print(f"DEBUG: Hashing password for {user_data.email}")
        hashed_password = hash_password(user_data.password)
        user_id = str(uuid.uuid4())
        current_time = get_utc_now()
        
        print(f"DEBUG: Creating user record for {user_data.email}")

        #Creo il token che verrà poi utilizzato per verificare la mail
        token = get_verification_token()

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
            "google_id": None,
            "verification_token": token
        }
        
        print(f"DEBUG: Inserting user into database")
        result = supabase_client.table("users").insert(new_user).execute()
        if not result.data:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "REGISTRATION_FAILED",
                    "message": "Failed to create user account"
                }
            )

        user_record_response = supabase_client.table("users").select("*").eq("email", user_data.email).execute()

        if not user_record_response.data:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "USER_NOT_FOUND",
                    "message": "User not found after creation"
                }
            )

        user_record = user_record_response.data[0]

        print(f"DEBUG: User created successfully: {user_record['id']}")
        print(f"DEBUG: Passing TOKEN {token} to {user_data.email}")

        # Invio email di verifica account
        email_task = send_verification_email_task.apply_async(
                kwargs={
                    'email_data': {
                        'to_email': user_data.email,
                        'username': user_record.get("full_name") if user_record.get("full_name") else user_data.email,
                        'verificationToken': user_record.get("verification_token"),
                    }
                },
                queue="emails",
                priority=6,
                retry=True,
                retry_policy={
                    'max_retries': 3,
                    'interval_start': 60,
                    'interval_step': 60,
                    'interval_max': 300
                }
            )

        # Rimuovi password hash e serializza datetime
        user_record_clean = user_record.copy()
        user_record_clean.pop("password_hash", None)
        user_record_serialized = serialize_datetime_fields(user_record_clean)
        
        print(f"DEBUG: Creating JWT tokens")
        access_token = create_access_token({"sub": user_record["email"], "user_id": user_record["id"]})
        refresh_token = create_refresh_token({"sub": user_record["email"], "user_id": user_record["id"]})
        
        print(f"DEBUG: Preparing JSON response")
        response_data = {
            "user": user_record_serialized,
            "message": "Registration completed successfully"
        }
        
        print(f"DEBUG: Creating JSONResponse")
        response = JSONResponse(content=response_data)
        
        print(f"DEBUG: Setting auth cookies")
        set_auth_cookies(response, access_token, refresh_token)
        
        # Log API call con gestione errori migliorata
        try:
            print(f"DEBUG: Logging API call")
            print(f"DEBUG: API call logged successfully")
        except Exception as log_error:
            print(f"WARNING: Failed to log API call: {str(log_error)}")
        
        print(f"DEBUG: Registration completed successfully for {user_data.email}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: Registration failed for {user_data.email}: {str(e)}")
        print(f"ERROR: Exception type: {type(e).__name__}")
        
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Internal server error"
            }
        )

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

@router.delete("/user/delete-account")
async def delete_user_account(
    request: Request,
    current_user: dict = Depends(get_current_user_from_cookie)
):
    """
    Richiesta di cancellazione account

    Strategia:
    1. Marca cancellation_request = TRUE
    2. Un job schedulato gestirà la cancellazione effettiva al termine dell'abbonamento
    3. Per utenti free: cancellazione immediata
    4. Per utenti premium: cancellazione differita a fine abbonamento
    """
    start_time = time.time()
    user_id = current_user.get("id")
    user_email = current_user.get("email")
    subscription_tier = current_user.get("subscription_tier", "free")

    debug_request_info(request)

    try:
        print(f"DEBUG: Starting account deletion request for user {user_id} ({user_email})")

        # Verifica che l'utente non abbia già richiesto la cancellazione
        if current_user.get("cancellation_request"):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "ALREADY_REQUESTED",
                    "message": "Account deletion already requested"
                }
            )

        current_time = get_utc_now()

        # Marca la richiesta di cancellazione
        cancellation_data = {
            "cancellation_request": True,
            "updated_at": current_time
        }

        print(f"DEBUG: Marking cancellation request for user: {user_id}")

        # Aggiorna il flag di cancellazione
        result = supabase_client.table("users").update(cancellation_data).eq("id", user_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "DELETION_REQUEST_FAILED",
                    "message": "Failed to request account deletion"
                }
            )

        print(f"DEBUG: Cancellation request marked successfully for {user_id}")

        # Log security event
        try:
            await log_security_event(
                supabase_client=supabase_client,
                event="account_deletion_requested",
                client_ip=api_logger._get_client_ip(request),
                details=f"User ID: {user_id}, Email: {user_email}, Tier: {subscription_tier}",
                user_id=user_id
            )
        except Exception as log_error:
            print(f"WARNING: Failed to log security event: {str(log_error)}")

        # Messaggio diverso in base al tipo di abbonamento
        if subscription_tier == "free":
            message = "Account deletion scheduled. Your account will be deleted shortly."
        else:
            message = "Account deletion scheduled. Your account will be deleted at the end of your subscription period."

        # Crea risposta e pulisci i cookie (logout)
        response_data = {
            "message": message,
            "cancellation_requested_at": current_time,
            "subscription_tier": subscription_tier
        }

        response = JSONResponse(content=response_data)
        clear_auth_cookies(response)

        # Log API call
        try:
            process_time = (time.time() - start_time) * 1000
            await api_logger.log_api_call(
                request=request,
                response_time=process_time,
                user_id=user_id,
                additional_data={
                    "action": "account_deletion_request",
                    "email": user_email[:50],
                    "subscription_tier": subscription_tier
                }
            )
        except Exception as log_error:
            print(f"WARNING: Failed to log API call: {str(log_error)}")

        print(f"DEBUG: Account deletion request completed for {user_id}")
        return response

    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: Account deletion request failed for {user_id}: {str(e)}")
        print(f"ERROR: Exception type: {type(e).__name__}")

        # Log errore
        try:
            process_time = (time.time() - start_time) * 1000
            await api_logger.log_api_call(
                request=request,
                response_time=process_time,
                user_id=user_id,
                error=str(e)[:200]
            )
        except Exception as log_error:
            print(f"WARNING: Failed to log error: {str(log_error)}")

        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to request account deletion. Please try again."
            }
        )

@router.post("/requestPasswordReset")
async def request_password_reset(email_data: VerificationEmailRequestRequest, request: Request):
    """Metodo per richiedere il reset password - invia email con token"""

    debug_request_info(request)
    start_time = time.time()

    try:
        if not email_data.email:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_EMAIL",
                    "message": "Email non valida"
                }
            )

        # Trova utente
        user_result = supabase_client.table("users").select("*").eq("email", email_data.email).execute()

        if not user_result.data:
            # Per sicurezza, non rivelare se l'email esiste o no
            # Restituisci sempre success
            return JSONResponse(content={"success": True})

        user_record = user_result.data[0]
        user_id = user_record["id"]

        # Genera sempre un nuovo token per ogni richiesta
        reset_token = get_verification_token()

        update_data = {
            "resetPassword_token": reset_token,
            "updated_at": get_utc_now()
        }

        # Salva il token su database
        supabase_client.table("users") \
            .update(update_data) \
            .eq("email", user_record["email"]) \
            .execute()

        # Invia email con il token di reset
        from app.workers.tasks import send_password_reset_email_task

        email_task = send_password_reset_email_task.apply_async(
            kwargs={
                'email_data': {
                    'to_email': email_data.email,
                    'username': user_record.get("full_name") if user_record.get("full_name") else email_data.email,
                    'resetToken': reset_token,
                }
            },
            queue="emails",
            priority=6,
            retry=True,
            retry_policy={
                'max_retries': 3,
                'interval_start': 60,
                'interval_step': 60,
                'interval_max': 300
            }
        )

        # Log security event
        try:
            await log_security_event(
                supabase_client=supabase_client,
                event="password_reset_requested",
                client_ip=api_logger._get_client_ip(request),
                details=f"Email: {email_data.email}",
                user_id=user_id
            )
        except Exception as log_error:
            print(f"WARNING: Failed to log security event: {str(log_error)}")

        response_data = {"success": True}
        print(f"DEBUG: Password reset requested for {email_data.email}")

        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: Password reset request failed: {str(e)}")
        print(f"ERROR: Exception type: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to process password reset request"
            }
        )

@router.post("/resetPassword")
async def reset_password(reset_data: dict, request: Request):
    """Metodo per completare il reset password con token"""

    debug_request_info(request)
    start_time = time.time()

    try:
        email = reset_data.get("email")
        token = reset_data.get("token")
        new_password = reset_data.get("newPassword")

        if not email or not token or not new_password:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "MISSING_FIELDS",
                    "message": "Email, token and new password are required"
                }
            )

        # Verifica lunghezza minima password
        if len(new_password) < 8:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "PASSWORD_TOO_SHORT",
                    "message": "Password must be at least 8 characters long"
                }
            )

        # Trova utente e verifica token
        user_result = supabase_client.table("users") \
            .select("*") \
            .eq("email", email) \
            .eq("resetPassword_token", token) \
            .execute()

        if not user_result.data:
            try:
                await log_security_event(
                    supabase_client=supabase_client,
                    event="password_reset_fail_invalid_token",
                    client_ip=api_logger._get_client_ip(request),
                    details=f"Email: {email}"
                )
            except Exception as log_error:
                print(f"WARNING: Failed to log security event: {str(log_error)}")

            raise HTTPException(
                status_code=401,
                detail={
                    "code": "INVALID_TOKEN",
                    "message": "Invalid or expired reset token"
                }
            )

        user_record = user_result.data[0]
        user_id = user_record["id"]

        # Hash della nuova password
        hashed_password = pwd_context.hash(new_password)

        # Aggiorna password e rimuovi il token di reset
        update_data = {
            "password_hash": hashed_password,
            "resetPassword_token": None,
            "updated_at": get_utc_now()
        }

        supabase_client.table("users") \
            .update(update_data) \
            .eq("id", user_id) \
            .execute()

        # Log security event
        try:
            await log_security_event(
                supabase_client=supabase_client,
                event="password_reset_completed",
                client_ip=api_logger._get_client_ip(request),
                details=f"User ID: {user_id}, Email: {email}",
                user_id=user_id
            )
        except Exception as log_error:
            print(f"WARNING: Failed to log security event: {str(log_error)}")

        response_data = {
            "success": True,
            "message": "Password reset successfully"
        }

        print(f"DEBUG: Password reset completed for {email}")
        return JSONResponse(content=response_data)

    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR: Password reset failed: {str(e)}")
        print(f"ERROR: Exception type: {type(e).__name__}")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Failed to reset password"
            }
        )

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