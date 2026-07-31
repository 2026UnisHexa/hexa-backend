import os
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_service import authenticate_user, create_user
from app.audio_service import (
    create_audio_url,
    delete_audio,
    download_audio,
    list_audio,
    update_audio_price,
    upload_audio,
)
from app.database import get_db
from app.jwt_service import create_access_token, get_current_login_id
from app.schemas import (
    AudioFilePriceResponse,
    AudioFileResponse,
    LoginRequest,
    LoginResponse,
    PriceUpdateRequest,
    SignupRequest,
    SignupResponse,
)


app = FastAPI(title="Hexa Backend")


def _cors_origins() -> list[str]:
    defaults = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://hexa-ten.vercel.app",
    ]
    extra = os.getenv("CORS_ORIGINS", "")
    for origin in extra.split(","):
        cleaned = origin.strip().rstrip("/")
        if cleaned and cleaned not in defaults:
            defaults.append(cleaned)
    return defaults


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    """
    Starlette's ServerErrorMiddleware sits outside CORSMiddleware, so bare
    unhandled exceptions become plain-text 500s with no ACAO header (browser
    reports a misleading CORS error). Return JSON from ExceptionMiddleware
    instead so CORS headers are still applied.
    """
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {exc}"},
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
        login_id=request.login_id,
        access_token=create_access_token(request.login_id),
    )


@app.post("/audio", response_model=AudioFileResponse, status_code=status.HTTP_201_CREATED)
async def create_audio(
    title: str = Form(...),
    price: float = Form(...),
    genreLabel: str | None = Form(None),
    chordLabel: str | None = Form(None),
    tempoBpm: int | None = Form(None),
    noteCount: int | None = Form(None),
    audioFile: UploadFile = File(...),
    login_id: str = Depends(get_current_login_id),
    db: Session = Depends(get_db),
):
    audio = await upload_audio(
        db,
        login_id,
        title,
        price,
        genreLabel,
        audioFile,
        chord_label=chordLabel,
        tempo_bpm=tempoBpm,
        note_count=noteCount,
    )
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
    contents, filename, content_type = download_audio(db, login_id, audio_id)
    return Response(
        content=contents,
        media_type=content_type,
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


@app.patch("/audio-files/{id}", response_model=AudioFilePriceResponse)
def patch_audio_price(
    id: str,
    request: PriceUpdateRequest,
    login_id: str = Depends(get_current_login_id),
    db: Session = Depends(get_db),
):
    audio = update_audio_price(db, login_id, id, request.price)
    return AudioFilePriceResponse(
        id=audio["id"],
        login_id=audio["loginId"],
        title=audio["title"],
        price=audio["price"],
        genre_label=audio["genreLabel"],
        created_at=audio["createdAt"],
    )


def _with_audio_url(audio: dict) -> dict:
    storage_path = audio.pop("_storagePath")
    audio["audioFile"] = create_audio_url(storage_path)
    return audio
