from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from jose import JWTError, jwt
import os
import requests
from app.core.config import settings
from app.core.supabase_client import supabase_client
import logging

logger = logging.getLogger(__name__)

auth_scheme = HTTPBearer()

async def get_current_user(token: str = Depends(auth_scheme)):
    try:
        # Decodifica token JWT usando la chiave pubblica di Supabase
        jwks_url = f"{os.getenv('SUPABASE_URL')}/auth/v1/keys"
        jwks = requests.get(jwks_url).json()

        unverified_header = jwt.get_unverified_header(token.credentials)
        key = next((k for k in jwks["keys"] if k["kid"] == unverified_header["kid"]), None)

        if not key:
            raise HTTPException(status_code=401, detail="Invalid auth key")

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        payload = jwt.decode(
            token.credentials,
            public_key,
            algorithms=["RS256"],
            audience=os.getenv("SUPABASE_URL")
        )

        return {
            "id": payload["sub"],
            "email": payload.get("email")
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# ================================
# NEW: Cookie-based authentication dependencies
# ================================

async def get_current_user_from_cookie(request: Request) -> dict:
    """
    Recupera l'utente dal cookie httpOnly JWT
    Utilizzato per proteggere gli endpoint API
    """
    access_token = request.cookies.get("access_token")

    if not access_token:
        logger.warning(f"No access_token cookie found for {request.url.path}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Authentication required. Please log in."
            }
        )

    try:
        payload = jwt.decode(access_token, settings.JWT_SECRET_KEY, algorithms=['HS256'])
        user_id = payload.get("user_id")
        token_type = payload.get("type")

        if not user_id or token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "INVALID_TOKEN",
                    "message": "Invalid authentication token"
                }
            )

        # Recupera i dati completi dell'utente dal database
        user_response = supabase_client.table("users").select("*").eq("id", user_id).execute()
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "USER_NOT_FOUND",
                    "message": "User not found"
                }
            )

        user = user_response.data[0]
        logger.debug(f"User authenticated: {user.get('email')}")
        return user

    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_TOKEN",
                "message": "Invalid or expired authentication token"
            }
        )

async def verify_email_verified(user: dict = Depends(get_current_user_from_cookie)) -> dict:
    """
    Verifica che l'utente abbia verificato la sua email
    """
    if not user.get("isVerified", False):
        logger.warning(f"Email not verified for user {user.get('email')}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "EMAIL_NOT_VERIFIED",
                "message": "Please verify your email address before using this feature"
            }
        )
    return user

async def verify_user_has_credits(user: dict = Depends(verify_email_verified)) -> dict:
    """
    Verifica che l'utente abbia crediti disponibili (check semplificato)
    Gli utenti premium hanno crediti illimitati
    La verifica precisa word-based avviene nell'endpoint dopo aver contato le parole
    """
    subscription_tier = user.get("subscription_tier", "free")
    credits_remaining = user.get("credits_remaining", 0)

    # Premium users hanno accesso illimitato
    if subscription_tier == "premium":
        logger.debug(f"Premium user {user.get('email')} - unlimited access")
        return user

    # Free users devono avere almeno 1 credito (verifica base)
    # La verifica precisa word-based avviene nell'endpoint
    if credits_remaining <= 0:
        logger.warning(f"No credits remaining for user {user.get('email')}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "NO_CREDITS",
                "message": "You have no credits remaining. Please upgrade to premium or wait for credit renewal.",
                "credits_remaining": 0,
                "subscription_tier": subscription_tier
            }
        )

    logger.debug(f"User {user.get('email')} has {credits_remaining} words remaining")
    return user

async def get_authenticated_user_with_credits(
    user: dict = Depends(verify_user_has_credits)
) -> dict:
    """
    Dependency completa per endpoint che richiedono:
    - Autenticazione JWT valida
    - Email verificata
    - Crediti disponibili (se free tier)

    Utilizzare questa dependency negli endpoint di text processing
    """
    return user
