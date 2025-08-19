from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
import jwt
import os
import requests

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
