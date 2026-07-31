from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_service import authenticate_user, create_user
from app.audio_service import (
    create_audio_url,
    delete_audio,
    download_audio,
    list_audio,
    upload_audio,
)
from app.database import get_db
from app.jwt_service import create_access_token, get_current_login_id
from app.schemas import AudioFileResponse, LoginRequest, LoginResponse, SignupRequest, SignupResponse


app = FastAPI(title="Hexa Backend")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://hexa-ten.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Hexa Backend is running"}


@app.get("/health/db")
def database_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@app.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup(request: SignupRequest, db: Session = Depends(get_db)):
    create_user(db, request.login_id, request.password)
    return SignupResponse(
        success=True,
        message="회원가입 성공",
        login_id=request.login_id,
    )


@app.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    if not authenticate_user(db, request.login_id, request.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="아이디 또는 비밀번호가 올바르지 않습니다.",
        )

    return LoginResponse(
        success=True,
        message="로그인 성공",
        loginId=request.login_id,
        accessToken=create_access_token(request.login_id),
    )


@app.post("/audio", response_model=AudioFileResponse, status_code=status.HTTP_201_CREATED)
async def create_audio(
    title: str = Form(...),
    price: float = Form(...),
    genreLabel: str | None = Form(None),
    audioFile: UploadFile = File(...),
    login_id: str = Depends(get_current_login_id),
    db: Session = Depends(get_db),
):
    audio = await upload_audio(db, login_id, title, price, genreLabel, audioFile)
    return _with_audio_url(audio)


@app.get("/audio", response_model=list[AudioFileResponse])
def get_audio_list(
    login_id: str = Depends(get_current_login_id),
    db: Session = Depends(get_db),
):
    return [_with_audio_url(audio) for audio in list_audio(db, login_id)]


@app.get("/audio/{audio_id}")
def get_audio(
    audio_id: str,
    login_id: str = Depends(get_current_login_id),
    db: Session = Depends(get_db),
):
    contents, filename = download_audio(db, login_id, audio_id)
    return Response(
        content=contents,
        media_type="audio/wav",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}"},
    )


@app.delete("/audio/{audio_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_audio(
    audio_id: str,
    login_id: str = Depends(get_current_login_id),
    db: Session = Depends(get_db),
):
    delete_audio(db, login_id, audio_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _with_audio_url(audio: dict) -> dict:
    storage_path = audio.pop("_storagePath")
    audio["audioFile"] = create_audio_url(storage_path)
    return audio
