import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


ALGORITHM = "HS256"
bearer_scheme = HTTPBearer(auto_error=False)


def _jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET이 설정되지 않았습니다.")
    return secret


def create_access_token(login_id: str) -> str:
    now = datetime.now(timezone.utc)
    try:
        expire_minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
    except ValueError as exc:
        raise RuntimeError("JWT_EXPIRE_MINUTES는 정수여야 합니다.") from exc
    payload = {
        "sub": login_id,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=ALGORITHM)


def get_current_login_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="유효한 로그인 토큰이 필요합니다.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized
    try:
        payload = jwt.decode(
            credentials.credentials,
            _jwt_secret(),
            algorithms=[ALGORITHM],
        )
        login_id = payload.get("sub")
        if not isinstance(login_id, str) or not login_id:
            raise unauthorized
        return login_id
    except jwt.PyJWTError as exc:
        raise unauthorized from exc
