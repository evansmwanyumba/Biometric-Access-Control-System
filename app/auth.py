import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi import Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from .database import get_db

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY not set. Check your .env file.")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/admin/login", auto_error=False)

# Roles, ordered here just for reference — no implicit hierarchy is assumed in code
SUPER_ADMIN = "SUPER_ADMIN"
ADMIN = "ADMIN"
SECURITY_OFFICER = "SECURITY_OFFICER"
GATE_PERSONNEL = "GATE_PERSONNEL"
GATE_DEVICE = "GATE_DEVICE"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


class CurrentAdmin:
    def __init__(self, username: str, role: str):
        self.username = username
        self.role = role


def get_current_admin(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> CurrentAdmin:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        access_token = token or request.cookies.get("access_token")
        if not access_token:
            raise credentials_exception
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        token_version: int = payload.get("ver", 0)
        if username is None or role is None:
            raise credentials_exception
        from .models import AdminUser

        user = db.query(AdminUser).filter(AdminUser.username == username).first()
        if (
            user is None
            or not user.is_active
            or user.role != role
            or user.token_version != token_version
        ):
            raise credentials_exception
        return CurrentAdmin(username=username, role=role)
    except JWTError:
        raise credentials_exception


def require_role(allowed_roles: List[str]):
    def role_checker(current: CurrentAdmin = Depends(get_current_admin)) -> CurrentAdmin:
        if current.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current.role}' is not permitted to perform this action",
            )
        return current
    return role_checker
