"""Password hashing (bcrypt) and stateless JWT session tokens (PyJWT)."""
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings

COOKIE_NAME = "access_token"
_ALGORITHM = "HS256"
_TOKEN_TTL = timedelta(days=7)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(UTC)
    payload = {"sub": user_id, "iat": now, "exp": now + _TOKEN_TTL}
    return jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[_ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
