from datetime import datetime

from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    login_id: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=4, max_length=128)


class LoginRequest(BaseModel):
    login_id: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class SignupResponse(BaseModel):
    success: bool
    message: str
    login_id: str


class LoginResponse(BaseModel):
    success: bool
    message: str
    login_id: str
    access_token: str
    token_type: str = "bearer"


class AudioFileResponse(BaseModel):
    id: str
    loginId: str
    title: str
    price: float
    genreLabel: str | None
    audioFile: str
    createdAt: datetime
