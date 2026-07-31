import os
from math import isfinite
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.orm import Session

load_dotenv()

MAX_AUDIO_SIZE = 50 * 1024 * 1024

# MediaRecorder / browsers often send video/webm or audio/webm;codecs=opus
_AUDIO_EXTENSIONS = {
    ".webm",
    ".weba",
    ".ogg",
    ".oga",
    ".wav",
    ".mp3",
    ".m4a",
    ".mp4",
    ".aac",
    ".flac",
}


def _bucket_name() -> str:
    name = (os.getenv("SUPABASE_AUDIO_BUCKET") or "").strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버 설정 오류: SUPABASE_AUDIO_BUCKET이 없습니다.",
        )
    return name


def _supabase_url() -> str:
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    if not url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버 설정 오류: SUPABASE_URL이 없습니다.",
        )
    return url


def _service_role_key() -> str:
    key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="서버 설정 오류: SUPABASE_SERVICE_ROLE_KEY가 없습니다.",
        )
    return key


def _storage_headers(*, content_type: str | None = None, upsert: bool | None = None) -> dict[str, str]:
    key = _service_role_key()
    headers = {
        "Authorization": f"Bearer {key}",
        "apikey": key,
    }
    if content_type:
        headers["Content-Type"] = content_type
    if upsert is not None:
        headers["x-upsert"] = "true" if upsert else "false"
    return headers


def _storage_error_detail(res: httpx.Response) -> str:
    body = (res.text or "").strip()
    if len(body) > 500:
        body = body[:500] + "…"
    return f"storage {res.status_code}" + (f": {body}" if body else "")


def _upload_object(storage_path: str, contents: bytes, content_type: str) -> None:
    """Upload via Storage REST to avoid supabase-py mangling error responses."""
    encoded = quote(storage_path, safe="/")
    url = f"{_supabase_url()}/storage/v1/object/{_bucket_name()}/{encoded}"
    try:
        res = httpx.post(
            url,
            content=contents,
            headers=_storage_headers(content_type=content_type, upsert=False),
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"음원 업로드 실패: storage 연결 오류 ({exc})",
        ) from exc
    if res.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"음원 업로드 실패: {_storage_error_detail(res)}",
        )


def _download_object(storage_path: str) -> bytes:
    encoded = quote(storage_path, safe="/")
    url = f"{_supabase_url()}/storage/v1/object/{_bucket_name()}/{encoded}"
    try:
        res = httpx.get(url, headers=_storage_headers(), timeout=60.0)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"음원 다운로드 실패: storage 연결 오류 ({exc})",
        ) from exc
    if res.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"음원 다운로드 실패: {_storage_error_detail(res)}",
        )
    return res.content


def _remove_object(storage_path: str) -> None:
    url = f"{_supabase_url()}/storage/v1/object/{_bucket_name()}"
    try:
        httpx.request(
            "DELETE",
            url,
            headers={**_storage_headers(), "Content-Type": "application/json"},
            json={"prefixes": [storage_path]},
            timeout=30.0,
        )
    except httpx.HTTPError:
        pass


def _create_signed_url(storage_path: str, expires_in: int = 3600) -> str:
    encoded = quote(storage_path, safe="/")
    url = f"{_supabase_url()}/storage/v1/object/sign/{_bucket_name()}/{encoded}"
    try:
        res = httpx.post(
            url,
            headers={**_storage_headers(), "Content-Type": "application/json"},
            json={"expiresIn": expires_in},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"음원 재생 URL 생성 실패: storage 연결 오류 ({exc})",
        ) from exc
    if res.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"음원 재생 URL 생성 실패: {_storage_error_detail(res)}",
        )
    try:
        data = res.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="음원 재생 URL 생성 실패: 잘못된 응답",
        ) from exc
    signed = data.get("signedURL") or data.get("signedUrl")
    if not isinstance(signed, str) or not signed:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="음원 재생 URL을 생성하지 못했습니다.",
        )
    if signed.startswith("http://") or signed.startswith("https://"):
        return signed
    return f"{_supabase_url()}/storage/v1{signed}"


def _normalize_audio_content_type(
    filename: str,
    declared: str | None,
) -> str:
    """Return a clean audio/* type acceptable to Storage."""
    raw = (declared or "").strip().lower()
    # Drop parameters: "audio/webm;codecs=opus" → "audio/webm"
    base = raw.split(";", 1)[0].strip() if raw else ""
    if base.startswith("audio/"):
        return base
    # Chrome MediaRecorder may label webm as video/webm
    if base in {"video/webm", "video/ogg", "application/ogg"}:
        return base.replace("video/", "audio/", 1) if base.startswith("video/") else "audio/ogg"
    guessed = guess_type(filename)[0]
    if guessed:
        g = guessed.split(";", 1)[0].strip().lower()
        if g.startswith("audio/"):
            return g
        if g == "video/webm":
            return "audio/webm"
        if g in {"video/ogg", "application/ogg"}:
            return "audio/ogg"
    ext = Path(filename).suffix.lower()
    if ext in _AUDIO_EXTENSIONS:
        return {
            ".webm": "audio/webm",
            ".weba": "audio/webm",
            ".ogg": "audio/ogg",
            ".oga": "audio/ogg",
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".mp4": "audio/mp4",
            ".aac": "audio/aac",
            ".flac": "audio/flac",
        }[ext]
    raise HTTPException(status_code=400, detail="오디오 파일만 업로드할 수 있습니다.")


def _ensure_user_exists(db: Session, login_id: str) -> None:
    exists = db.execute(
        text("SELECT 1 FROM users WHERE login_id = :login_id"),
        {"login_id": login_id},
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자가 없습니다.")


def _normalize_optional_str(value: str | None, *, max_len: int, label: str) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise HTTPException(
            status_code=400,
            detail=f"{label}은(는) {max_len}자 이하여야 합니다.",
        )
    return cleaned


async def upload_audio(
    db: Session,
    login_id: str,
    title: str,
    price: float,
    genre_label: str | None,
    file: UploadFile,
    *,
    chord_label: str | None = None,
    tempo_bpm: int | None = None,
    note_count: int | None = None,
) -> dict:
    _ensure_user_exists(db, login_id)
    title = title.strip()
    genre_label = _normalize_optional_str(genre_label, max_len=100, label="장르")
    chord_label = _normalize_optional_str(chord_label, max_len=200, label="코드 라벨")

    if not title or len(title) > 200:
        raise HTTPException(status_code=400, detail="제목은 1~200자여야 합니다.")
    if not isfinite(price) or price < 0:
        raise HTTPException(status_code=400, detail="가격은 0 이상이어야 합니다.")
    if tempo_bpm is not None and not (40 <= tempo_bpm <= 240):
        raise HTTPException(status_code=400, detail="템포는 40~240 BPM이어야 합니다.")
    if note_count is not None and note_count < 0:
        raise HTTPException(status_code=400, detail="노트 수는 0 이상이어야 합니다.")

    filename = Path(file.filename or "audio").name
    content_type = _normalize_audio_content_type(filename, file.content_type)

    contents = await file.read(MAX_AUDIO_SIZE + 1)
    if len(contents) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기는 50MB 이하여야 합니다.")
    if not contents:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")

    audio_id = uuid4()
    extension = Path(filename).suffix.lower() or ".webm"
    if extension not in _AUDIO_EXTENSIONS:
        extension = ".webm"
    storage_path = f"{login_id}/{audio_id}{extension}"
    try:
        _upload_object(storage_path, contents, content_type)
        row = db.execute(
            text(
                """
                INSERT INTO audio_files
                    (id, login_id, storage_path, title, price, genre_label,
                     chord_label, tempo_bpm, note_count,
                     original_filename, size_bytes)
                VALUES
                    (:id, :login_id, :storage_path, :title, :price, :genre_label,
                     :chord_label, :tempo_bpm, :note_count,
                     :original_filename, :size_bytes)
                RETURNING id, login_id, storage_path, title, price, genre_label,
                          chord_label, tempo_bpm, note_count, created_at
                """
            ),
            {
                "id": audio_id,
                "login_id": login_id,
                "storage_path": storage_path,
                "title": title,
                "price": price,
                "genre_label": genre_label,
                "chord_label": chord_label,
                "tempo_bpm": tempo_bpm,
                "note_count": note_count,
                "original_filename": filename,
                "size_bytes": len(contents),
            },
        ).mappings().one()
        db.commit()
    except HTTPException:
        db.rollback()
        _remove_object(storage_path)
        raise
    except Exception as exc:
        db.rollback()
        _remove_object(storage_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"음원 업로드 실패: {exc}",
        ) from exc
    return _serialize(row)


def list_audio(db: Session, login_id: str) -> list[dict]:
    _ensure_user_exists(db, login_id)
    rows = db.execute(
        text(
            """
            SELECT id, login_id, storage_path, title, price, genre_label,
                   chord_label, tempo_bpm, note_count, created_at
            FROM audio_files
            WHERE login_id = :login_id
            ORDER BY created_at DESC
            """
        ),
        {"login_id": login_id},
    ).mappings()
    return [_serialize(row) for row in rows]


def download_audio(db: Session, login_id: str, audio_id: str) -> tuple[bytes, str, str]:
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
    data = _download_object(row["storage_path"])
    filename = row["original_filename"]
    content_type = guess_type(filename)[0] or "application/octet-stream"
    return data, filename, content_type


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

    storage_path = row["storage_path"]
    # DB first so we never keep metadata pointing at a deleted object.
    db.execute(
        text("DELETE FROM audio_files WHERE id = :id AND login_id = :login_id"),
        {"id": audio_id, "login_id": login_id},
    )
    db.commit()
    _remove_object(storage_path)


def update_audio_price(
    db: Session,
    login_id: str,
    audio_id: str,
    price: float,
) -> dict:
    if not isfinite(price) or price < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="가격은 0 이상이어야 합니다.",
        )

    row = db.execute(
        text(
            """
            SELECT id, login_id, storage_path, title, price, genre_label,
                   chord_label, tempo_bpm, note_count, created_at
            FROM audio_files
            WHERE id = :id
            """
        ),
        {"id": audio_id},
    ).mappings().one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="음원 파일이 없습니다.",
        )

    if row["login_id"] != login_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 작품만 수정할 수 있습니다.",
        )

    updated = db.execute(
        text(
            """
            UPDATE audio_files
            SET price = :price
            WHERE id = :id
            RETURNING id, login_id, storage_path, title, price, genre_label,
                      chord_label, tempo_bpm, note_count, created_at
            """
        ),
        {"id": audio_id, "price": price},
    ).mappings().one()
    db.commit()
    return _serialize(updated)


def _serialize(row) -> dict:
    result = {
        "id": str(row["id"]),
        "loginId": row["login_id"],
        "title": row["title"],
        "price": float(row["price"]),
        "genreLabel": row["genre_label"],
        "chordLabel": row["chord_label"] if "chord_label" in row else None,
        "tempoBpm": row["tempo_bpm"] if "tempo_bpm" in row else None,
        "noteCount": row["note_count"] if "note_count" in row else None,
        "createdAt": row["created_at"],
    }
    if "storage_path" in row:
        result["_storagePath"] = row["storage_path"]
    return result


def create_audio_url(storage_path: str) -> str:
    return _create_signed_url(storage_path, 3600)
