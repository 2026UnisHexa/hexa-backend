import os
from math import isfinite
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.orm import Session
from supabase import Client, create_client


BUCKET_NAME = os.getenv("SUPABASE_AUDIO_BUCKET")
MAX_AUDIO_SIZE = 50 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"audio/wav", "audio/wave", "audio/x-wav"}


def _storage_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not service_role_key:
        raise RuntimeError(
            "SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY가 설정되지 않았습니다."
        )
    return create_client(url, service_role_key)


def _ensure_user_exists(db: Session, login_id: str) -> None:
    exists = db.execute(
        text("SELECT 1 FROM users WHERE login_id = :login_id"),
        {"login_id": login_id},
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자가 없습니다.")


async def upload_audio(
    db: Session,
    login_id: str,
    title: str,
    price: float,
    genre_label: str | None,
    file: UploadFile,
) -> dict:
    _ensure_user_exists(db, login_id)
    title = title.strip()
    genre_label = genre_label.strip() if genre_label else None
    if not title or len(title) > 200:
        raise HTTPException(status_code=400, detail="제목은 1~200자여야 합니다.")
    if genre_label and len(genre_label) > 100:
        raise HTTPException(status_code=400, detail="장르는 100자 이하여야 합니다.")
    if not isfinite(price) or price < 0:
        raise HTTPException(status_code=400, detail="가격은 0 이상이어야 합니다.")
    filename = Path(file.filename or "audio.wav").name
    if Path(filename).suffix.lower() != ".wav":
        raise HTTPException(status_code=400, detail="WAV 파일만 업로드할 수 있습니다.")
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="WAV 파일 형식이 아닙니다.")

    contents = await file.read(MAX_AUDIO_SIZE + 1)
    if len(contents) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기는 50MB 이하여야 합니다.")
    if len(contents) < 12 or contents[:4] != b"RIFF" or contents[8:12] != b"WAVE":
        raise HTTPException(status_code=400, detail="올바른 WAV 파일이 아닙니다.")

    audio_id = uuid4()
    storage_path = f"{login_id}/{audio_id}.wav"
    try:
        _storage_client().storage.from_(BUCKET_NAME).upload(
            path=storage_path,
            file=contents,
            file_options={"content-type": "audio/wav", "upsert": "false"},
        )
        row = db.execute(
            text(
                """
                INSERT INTO audio_files
                    (id, login_id, storage_path, title, price, genre_label,
                     original_filename, size_bytes)
                VALUES
                    (:id, :login_id, :storage_path, :title, :price, :genre_label,
                     :original_filename, :size_bytes)
                RETURNING id, login_id, storage_path, title, price, genre_label,
                          created_at
                """
            ),
            {
                "id": audio_id,
                "login_id": login_id,
                "storage_path": storage_path,
                "title": title,
                "price": price,
                "genre_label": genre_label,
                "original_filename": filename,
                "size_bytes": len(contents),
            },
        ).mappings().one()
        db.commit()
    except Exception:
        db.rollback()
        try:
            _storage_client().storage.from_(BUCKET_NAME).remove([storage_path])
        except Exception:
            pass
        raise
    return _serialize(row)


def list_audio(db: Session, login_id: str) -> list[dict]:
    _ensure_user_exists(db, login_id)
    rows = db.execute(
        text(
            """
            SELECT id, login_id, storage_path, title, price, genre_label, created_at
            FROM audio_files
            WHERE login_id = :login_id
            ORDER BY created_at DESC
            """
        ),
        {"login_id": login_id},
    ).mappings()
    return [_serialize(row) for row in rows]


def download_audio(db: Session, login_id: str, audio_id: str) -> tuple[bytes, str]:
    row = db.execute(
        text(
            """
            SELECT storage_path, original_filename
            FROM audio_files
            WHERE id = :id AND login_id = :login_id
            """
        ),
        {"id": audio_id, "login_id": login_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="음원 파일이 없습니다.")
    data = _storage_client().storage.from_(BUCKET_NAME).download(row["storage_path"])
    return data, row["original_filename"]


def delete_audio(db: Session, login_id: str, audio_id: str) -> None:
    row = db.execute(
        text(
            """
            SELECT storage_path FROM audio_files
            WHERE id = :id AND login_id = :login_id
            """
        ),
        {"id": audio_id, "login_id": login_id},
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="음원 파일이 없습니다.")
    _storage_client().storage.from_(BUCKET_NAME).remove([row["storage_path"]])
    db.execute(text("DELETE FROM audio_files WHERE id = :id"), {"id": audio_id})
    db.commit()


def _serialize(row) -> dict:
    result = {
        "id": str(row["id"]),
        "loginId": row["login_id"],
        "title": row["title"],
        "price": float(row["price"]),
        "genreLabel": row["genre_label"],
        "createdAt": row["created_at"],
    }
    if "storage_path" in row:
        result["_storagePath"] = row["storage_path"]
    return result


def create_audio_url(storage_path: str) -> str:
    response = (
        _storage_client()
        .storage.from_(BUCKET_NAME)
        .create_signed_url(storage_path, 3600)
    )
    signed_url = response.get("signedUrl") or response.get("signedURL")
    if not signed_url:
        raise RuntimeError("음원 재생 URL을 생성하지 못했습니다.")
    return signed_url
