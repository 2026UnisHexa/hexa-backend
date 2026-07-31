from fastapi import HTTPException, status
from pwdlib import PasswordHash
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


password_hasher = PasswordHash.recommended()


def create_user(db: Session, login_id: str, password: str) -> None:
    password_hash = password_hasher.hash(password)

    try:
        db.execute(
            text(
                """
                INSERT INTO users (login_id, password_hash)
                VALUES (:login_id, :password_hash)
                """
            ),
            {"login_id": login_id, "password_hash": password_hash},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 사용 중인 아이디입니다.",
        ) from exc


def authenticate_user(db: Session, login_id: str, password: str) -> bool:
    stored_hash = db.execute(
        text(
            """
            SELECT password_hash
            FROM users
            WHERE login_id = :login_id
            """
        ),
        {"login_id": login_id},
    ).scalar_one_or_none()

    if stored_hash is None:
        return False

    return password_hasher.verify(password, stored_hash)
