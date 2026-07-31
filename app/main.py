from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_service import authenticate_user, create_user
from app.database import get_db
from app.schemas import AuthResponse, LoginRequest, SignupRequest


app = FastAPI(title="Hexa Backend")


@app.get("/")
def root():
    return {"message": "Hexa Backend is running"}


@app.get("/health/db")
def database_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(request: SignupRequest, db: Session = Depends(get_db)):
    create_user(db, request.login_id, request.password)
    return AuthResponse(
        success=True,
        message="회원가입 성공",
        login_id=request.login_id,
    )


@app.post("/login", response_model=AuthResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    if not authenticate_user(db, request.login_id, request.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    return AuthResponse(
        success=True,
        message="로그인 성공",
        login_id=request.login_id,
    )

