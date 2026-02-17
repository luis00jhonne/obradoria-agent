"""
Autenticação JWT - valida Bearer token nas requisições.
O token é gerado pelo backend Java; aqui apenas verificamos a assinatura.
"""

import base64

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.config import get_settings
from app.api.context import request_token

security = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Valida o JWT Bearer token.
    Seta o token no contexto para uso nas chamadas à API Spring.
    Retorna o payload decodificado se válido.
    Levanta HTTPException 401 se inválido ou expirado.
    """
    token = credentials.credentials
    settings = get_settings()

    try:
        # Java base64-decodifica o secret antes de assinar
        secret_bytes = base64.b64decode(settings.jwt_secret)
        payload = jwt.decode(
            token,
            secret_bytes,
            algorithms=["HS256", "HS384", "HS512"],
        )
        # Disponibilizar token para camadas internas (spring_client)
        request_token.set(token)
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expirado",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )
