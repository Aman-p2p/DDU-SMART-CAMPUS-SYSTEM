from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from typing import Optional

from ..core.database import get_db
from ..core.config import get_settings
from ..models.models import User, UserRole

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
settings = get_settings()

class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict

class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    department: Optional[str] = None
    branch: Optional[str] = None
    academic_year: Optional[int] = None
    section: Optional[str] = None
    is_test_data: Optional[bool] = True

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password[:72])

def verify_password(plain, hashed):
    try:
        return pwd_context.verify(plain[:72], hashed)
    except Exception:
        return False

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.email == email).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user

@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Requirement 2 & Universal Password: Trinetra123@ across all roles
    username = (form_data.username or "").strip()
    if not username or username in ("default", "admin"):
        username = "admin@ddugu.ac.in"
    password = (form_data.password or "").strip() or "Trinetra123@"

    user = db.query(User).filter(User.email == username).first()
    if not user:
        if username in ("admin@ddugu.ac.in", "admin"):
            user = db.query(User).filter(User.role == UserRole.ADMIN).first()
        elif username in ("faculty@ddugu.ac.in", "faculty"):
            user = db.query(User).filter(User.role == UserRole.FACULTY).first()
        elif username in ("student@ddugu.ac.in", "student"):
            user = db.query(User).filter(User.role == UserRole.STUDENT).first()
        elif username in ("staff@ddugu.ac.in", "staff"):
            user = db.query(User).filter(User.role == UserRole.STAFF).first()

    if not user:
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    # Accept universal password Trinetra123@ for all roles, or valid bcrypt hash / test passwords
    valid_passwords = {"Trinetra123@", "Faculty@DDUGU2026", "Student@DDUGU2026", "Trinetra@Admin2026"}
    if password not in valid_passwords and not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
            
    token = create_access_token({"sub": user.email, "role": user.role.value})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value or "admin",
            "department": user.department,
            "branch": user.branch,
            "academic_year": user.academic_year,
            "section": user.section,
            "is_test_data": getattr(user, "is_test_data", True)
        }
    }

@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role.value,
        department=current_user.department,
        branch=current_user.branch,
        academic_year=current_user.academic_year,
        section=current_user.section,
        is_test_data=getattr(current_user, "is_test_data", True)
    )
