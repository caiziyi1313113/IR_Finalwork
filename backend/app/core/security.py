from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.database import get_db
from app.models.user import User

try:
    from passlib.context import CryptContext
except ModuleNotFoundError:  # pragma: no cover
    CryptContext = None  # type: ignore[assignment]

# 安全认证模块
# 用户密码加密、JWT Token 生成/验证，以及 FastAPI 的身份认证依赖注入
# Use a pure-Python hash as the primary scheme to avoid bcrypt backend
# compatibility problems inside the container. This is sufficient for the
# course project and does not require rebuilding native extensions.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _resolve_user_from_token(token: str, db: Session) -> User | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
    return db.scalar(select(User).where(User.id == user_id))


def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    return _resolve_user_from_token(credentials.credentials, db)


def get_current_user_required(
    current_user: User | None = Depends(get_current_user_optional),
) -> User:
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或 token 无效")
    return current_user


CurrentUser = Annotated[User | None, Depends(get_current_user_optional)]
