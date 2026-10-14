import cv2
import numpy as np
import face_recognition
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request, Response, Query
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
from starlette.staticfiles import StaticFiles

import re
import json
import logging
import threading
import traceback
from pathlib import Path

from .database import engine, Base, get_db, SessionLocal
from .models import Student, FaceEmbedding, AccessLog, AdminUser, Camera, ActivityLog
from .services import engine_instance
from .crypto_utils import encrypt_bytes, encrypt_text, decrypt_text
from .liveness import liveness_detector
from . import auth
from .auth import require_role, get_current_admin, CurrentAdmin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("facialrec")
SYSTEM_STATE_LOCK = threading.RLock()
SYSTEM_GENERATION = 0
CAMERA_STREAMS: dict[str, list[cv2.VideoCapture]] = {}
CAMERA_GENERATIONS: dict[str, int] = {}
CAMERA_STATE_LOCK = threading.RLock()
WEBCAM_STATUS = "OFFLINE"

Base.metadata.create_all(bind=engine)


def migrate_legacy_tables() -> None:
    """Bring earlier local database schemas forward without dropping user data."""
    with engine.begin() as connection:
        admin_sql = connection.execute(
            text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'admin_users'")
        ).scalar_one_or_none() or ""
        if "GATE_PERSONNEL" not in admin_sql:
            connection.exec_driver_sql(
                """
                CREATE TABLE admin_users_new (
                    id INTEGER NOT NULL PRIMARY KEY,
                    username VARCHAR NOT NULL,
                    hashed_password VARCHAR NOT NULL,
                    role VARCHAR NOT NULL,
                    is_active INTEGER,
                    created_at DATETIME,
                    token_version INTEGER NOT NULL DEFAULT 0,
                    CONSTRAINT ck_admin_role CHECK (
                        role IN ('SUPER_ADMIN', 'ADMIN', 'SECURITY_OFFICER', 'GATE_PERSONNEL', 'GATE_DEVICE')
                    ),
                    CONSTRAINT ck_admin_is_active CHECK (is_active IN (0, 1))
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO admin_users_new (id, username, hashed_password, role, is_active, created_at, token_version)
                SELECT id, username, hashed_password, role, is_active, created_at, 0 FROM admin_users
                """
            )
            connection.exec_driver_sql("DROP TABLE admin_users")
            connection.exec_driver_sql("ALTER TABLE admin_users_new RENAME TO admin_users")
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX ix_admin_users_username ON admin_users (username)"
            )
            connection.exec_driver_sql("CREATE INDEX ix_admin_users_id ON admin_users (id)")
        admin_columns = {
            column["name"] for column in inspect(connection).get_columns("admin_users")
        }
        if "token_version" not in admin_columns:
            connection.exec_driver_sql(
                "ALTER TABLE admin_users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
            )

        camera_table_names = {
            column["name"] for column in inspect(connection).get_columns("cameras")
        }
        if "encrypted_url" not in camera_table_names:
            connection.exec_driver_sql("ALTER TABLE cameras ADD COLUMN encrypted_url BLOB")
        if "is_active" not in camera_table_names:
            connection.exec_driver_sql(
                "ALTER TABLE cameras ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
            )
        if "camera_url" in camera_table_names:
            camera_rows = connection.execute(
                text(
                    "SELECT camera_id, camera_url FROM cameras "
                    "WHERE encrypted_url IS NULL"
                )
            ).all()
            for camera_id, camera_url in camera_rows:
                connection.execute(
                    text(
                        "UPDATE cameras SET encrypted_url = :encrypted_url, camera_url = '' "
                        "WHERE camera_id = :camera_id"
                    ),
                    {
                        "encrypted_url": encrypt_text(camera_url),
                        "camera_id": camera_id,
                    },
                )


migrate_legacy_tables()

app = FastAPI(title="Biometric Access Control API")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}\n"
        + traceback.format_exc()
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again or contact an administrator."}
    )

# --- Pydantic Schemas ---
from enum import Enum

class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"

class AdminRole(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    SECURITY_OFFICER = "SECURITY_OFFICER"
    GATE_PERSONNEL = "GATE_PERSONNEL"
    GATE_DEVICE = "GATE_DEVICE"

STUDENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9\-]{3,20}$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{3,32}$")

class StudentCreate(BaseModel):
    student_id: str = Field(..., min_length=3, max_length=20)
    full_name: str = Field(..., min_length=1, max_length=100)
    course: str = Field(..., min_length=1, max_length=100)
    status: StudentStatus = StudentStatus.ACTIVE

    @field_validator("student_id")
    @classmethod
    def validate_student_id(cls, v: str) -> str:
        v = v.strip()
        if not STUDENT_ID_PATTERN.match(v):
            raise ValueError("student_id must be 3-20 alphanumeric characters or hyphens")
        return v

    @field_validator("full_name", "course")
    @classmethod
    def validate_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("This field cannot be blank or whitespace-only")
        return v

class StudentUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=100)
    course: Optional[str] = Field(None, min_length=1, max_length=100)
    status: Optional[StudentStatus] = None

    @field_validator("full_name", "course")
    @classmethod
    def validate_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("This field cannot be blank or whitespace-only")
        return v

class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=72)
    role: AdminRole

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        v = v.strip()
        if not USERNAME_PATTERN.match(v):
            raise ValueError("username must be 3-32 characters: letters, numbers, underscore, hyphen only")
        return v

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        if not re.search(r"[A-Za-z]", v) or not re.search(r"[0-9]", v):
            raise ValueError("password must contain both letters and numbers")
        return v


class AccountUpdate(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=72)
    username: Optional[str] = Field(None, min_length=3, max_length=32)
    new_password: Optional[str] = Field(None, min_length=8, max_length=72)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            value = value.strip()
            if not USERNAME_PATTERN.fullmatch(value):
                raise ValueError("username must be 3-32 characters: letters, numbers, underscore, hyphen only")
        return value

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and (
            not re.search(r"[A-Za-z]", value) or not re.search(r"[0-9]", value)
        ):
            raise ValueError("password must contain both letters and numbers")
        return value

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

CAMERA_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


class CameraCreate(BaseModel):
    camera_id: str = Field(..., min_length=3, max_length=32)
    camera_name: str = Field(..., min_length=1, max_length=80)
    rtsp_url: str = Field(..., min_length=10, max_length=1024)

    @field_validator("camera_id")
    @classmethod
    def validate_camera_id(cls, value: str) -> str:
        value = value.strip()
        if not CAMERA_ID_PATTERN.fullmatch(value):
            raise ValueError("camera_id may contain only letters, numbers, hyphens, and underscores")
        if value.lower() == "webcam":
            raise ValueError("'webcam' is reserved for the laptop webcam")
        return value

    @field_validator("camera_name")
    @classmethod
    def validate_camera_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("camera_name cannot be blank")
        return value

    @field_validator("rtsp_url")
    @classmethod
    def validate_rtsp_url(cls, value: str) -> str:
        value = value.strip()
        if not value.lower().startswith(("rtsp://", "rtsps://")):
            raise ValueError("rtsp_url must start with rtsp:// or rtsps://")
        return value


class CameraUpdate(BaseModel):
    camera_name: Optional[str] = Field(None, min_length=1, max_length=80)
    rtsp_url: Optional[str] = Field(None, min_length=10, max_length=1024)

    @field_validator("camera_name")
    @classmethod
    def validate_camera_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("camera_name cannot be blank")
        return value

    @field_validator("rtsp_url")
    @classmethod
    def validate_rtsp_url(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            value = value.strip()
            if not value.lower().startswith(("rtsp://", "rtsps://")):
                raise ValueError("rtsp_url must start with rtsp:// or rtsps://")
        return value


STATIC_DIR = Path(__file__).resolve().parent / "static"
CAMERA_VIEW_ROLES = [
    auth.SUPER_ADMIN,
    auth.ADMIN,
    auth.SECURITY_OFFICER,
    auth.GATE_PERSONNEL,
    auth.GATE_DEVICE,
]
CAMERA_MANAGEMENT_ROLES = [auth.SUPER_ADMIN, auth.ADMIN]
LOG_VIEW_ROLES = [
    auth.SUPER_ADMIN,
    auth.ADMIN,
    auth.SECURITY_OFFICER,
    auth.GATE_PERSONNEL,
]
LOG_DELETE_ROLES = [auth.SUPER_ADMIN, auth.ADMIN]
USER_MANAGEMENT_ROLES = [auth.SUPER_ADMIN, auth.ADMIN]


def record_activity(
    db: Session,
    actor_username: str,
    actor_role: str,
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    db.add(
        ActivityLog(
            actor_username=actor_username,
            actor_role=actor_role,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=json.dumps(details, sort_keys=True) if details else None,
        )
    )


def record_actor_activity(
    db: Session,
    actor: CurrentAdmin,
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    record_activity(
        db,
        actor.username,
        actor.role,
        action,
        entity_type,
        entity_id,
        details,
    )


# --- Application Startup ---
@app.on_event("startup")
def startup_event():
    db = next(get_db())
    try:
        engine_instance.reload_cache(db)
        stale_cameras = db.query(Camera).filter(Camera.status == "ONLINE").all()
        for camera in stale_cameras:
            camera.status = "OFFLINE"
            record_activity(
                db,
                "SYSTEM",
                "SYSTEM",
                "CAMERA_MARKED_OFFLINE_ON_STARTUP",
                "camera",
                camera.camera_id,
                {"camera_name": camera.camera_name},
            )
        if stale_cameras:
            db.commit()
    finally:
        db.close()

# --- Auth ---
@app.post("/api/admin/login", response_model=Token)
@limiter.limit("5/minute")
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(AdminUser).filter(AdminUser.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        record_activity(
            db,
            form_data.username[:32],
            "UNKNOWN",
            "LOGIN_FAILED",
            "account",
            form_data.username[:32],
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    if not user.is_active:
        record_activity(
            db,
            user.username,
            user.role,
            "LOGIN_BLOCKED",
            "account",
            user.username,
            {"reason": "disabled account"},
        )
        db.commit()
        raise HTTPException(status_code=403, detail="Account is disabled")

    record_activity(db, user.username, user.role, "LOGIN_SUCCEEDED", "account", user.username)
    token = auth.create_access_token(
        data={"sub": user.username, "role": user.role, "ver": user.token_version}
    )
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        max_age=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    return Token(access_token=token)

@app.post("/api/admin/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(get_current_admin),
):
    record_actor_activity(db, current, "LOGOUT", "account", current.username)
    db.commit()
    response.delete_cookie("access_token", path="/", samesite="strict")
    return {"message": "Logged out"}

@app.get("/api/admin/me")
def get_current_user(current: CurrentAdmin = Depends(get_current_admin)):
    return {"username": current.username, "role": current.role}


@app.patch("/api/admin/account")
def update_own_account(
    payload: AccountUpdate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(get_current_admin),
):
    user = db.query(AdminUser).filter(AdminUser.username == current.username).first()
    if user is None or not auth.verify_password(
        payload.current_password, user.hashed_password
    ):
        raise HTTPException(status_code=403, detail="Current password is incorrect")

    new_username = payload.username or user.username
    if new_username == user.username and payload.new_password is None:
        raise HTTPException(
            status_code=400,
            detail="Provide a new username or a new password",
        )
    if new_username != user.username and db.query(AdminUser).filter(
        AdminUser.username == new_username
    ).first():
        raise HTTPException(status_code=409, detail="Username is already in use")

    user.username = new_username
    if payload.new_password is not None:
        user.hashed_password = auth.hash_password(payload.new_password)
    user.token_version += 1
    record_activity(
        db,
        current.username,
        current.role,
        "ACCOUNT_CREDENTIALS_UPDATED",
        "account",
        user.username,
        {"username_changed": new_username != current.username, "password_changed": payload.new_password is not None},
    )
    db.commit()

    token = auth.create_access_token(
        data={"sub": user.username, "role": user.role, "ver": user.token_version}
    )
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        max_age=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    return {
        "message": "Account credentials updated. Other active sessions have been signed out.",
        "username": user.username,
        "role": user.role,
    }


# --- User and system administration ---
@app.get("/api/admin/users")
def list_admin_users(
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(USER_MANAGEMENT_ROLES)),
):
    query = db.query(AdminUser)
    if current.role == auth.ADMIN:
        query = query.filter(AdminUser.role.in_([auth.GATE_PERSONNEL, auth.GATE_DEVICE]))
    users = query.order_by(AdminUser.username.asc()).all()
    return [
        {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "is_active": bool(user.is_active),
        }
        for user in users
    ]

@app.post("/api/admin/users")
def create_admin_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(USER_MANAGEMENT_ROLES))
):
    if current.role == auth.ADMIN and payload.role not in (
        AdminRole.GATE_PERSONNEL,
        AdminRole.GATE_DEVICE,
    ):
        raise HTTPException(
            status_code=403,
            detail="Admins may create only gate personnel and gate device accounts",
        )
    if db.query(AdminUser).filter(AdminUser.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    new_user = AdminUser(
        username=payload.username,
        hashed_password=auth.hash_password(payload.password),
        role=payload.role.value,
        is_active=1
    )
    db.add(new_user)
    record_actor_activity(
        db,
        current,
        "ACCOUNT_CREATED",
        "account",
        payload.username,
        {"role": payload.role.value},
    )
    db.commit()
    return {"message": f"Admin user '{payload.username}' created with role {payload.role.value}"}


@app.delete("/api/admin/users/{username}")
def delete_admin_user(
    username: str,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(USER_MANAGEMENT_ROLES)),
):
    user = db.query(AdminUser).filter(AdminUser.username == username).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User account not found")
    if user.username == current.username:
        raise HTTPException(status_code=400, detail="You cannot delete the account you are using")
    if current.role == auth.ADMIN and user.role not in (
        auth.GATE_PERSONNEL,
        auth.GATE_DEVICE,
    ):
        raise HTTPException(status_code=403, detail="Only a super admin may delete admin accounts")
    record_actor_activity(
        db,
        current,
        "ACCOUNT_DELETED",
        "account",
        user.username,
        {"role": user.role},
    )
    db.delete(user)
    db.commit()
    return {"message": f"Account '{username}' deleted"}


@app.delete("/api/admin/system/wipe")
def wipe_system(
    response: Response,
    confirmation: str = Query(...),
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role([auth.SUPER_ADMIN])),
):
    global SYSTEM_GENERATION, WEBCAM_STATUS

    if confirmation != "WIPE EVERYTHING":
        raise HTTPException(
            status_code=400,
            detail='Confirmation must exactly match "WIPE EVERYTHING"',
        )

    db.commit()
    with SYSTEM_STATE_LOCK:
        SYSTEM_GENERATION += 1
        WEBCAM_STATUS = "OFFLINE"
        with CAMERA_STATE_LOCK:
            for streams in CAMERA_STREAMS.values():
                for stream in streams:
                    stream.release()
            CAMERA_STREAMS.clear()
            CAMERA_GENERATIONS.clear()
        with engine.begin() as connection:
            table_names = inspect(connection).get_table_names()
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
            deleted_rows = {}
            for table_name in table_names:
                if table_name.startswith("sqlite_"):
                    continue
                quoted_name = engine.dialect.identifier_preparer.quote(table_name)
                result = connection.exec_driver_sql(f"DELETE FROM {quoted_name}")
                deleted_rows[table_name] = result.rowcount
            sequence_table = connection.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
            ).scalar()
            if sequence_table:
                connection.exec_driver_sql("DELETE FROM sqlite_sequence")
        engine_instance.clear_cache()
        liveness_detector.reset()
    response.delete_cookie("access_token", path="/", samesite="strict")
    return {"message": "System data wiped", "deleted_rows": deleted_rows}

# --- Admin Operations: Student Management ---
@app.get("/api/admin/students")
def list_students(
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role([auth.SUPER_ADMIN, auth.ADMIN])),
):
    students = db.query(Student).order_by(Student.created_at.desc()).all()
    return [
        {
            "student_id": student.student_id,
            "full_name": student.full_name,
            "course": student.course,
            "status": student.status,
            "created_at": student.created_at.isoformat() if student.created_at else None,
        }
        for student in students
    ]


@app.get("/api/admin/students/{student_id}")
def get_student(
    student_id: str,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role([auth.SUPER_ADMIN, auth.ADMIN])),
):
    student = db.query(Student).filter(Student.student_id == student_id).first()
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    record_actor_activity(
        db,
        current,
        "STUDENT_RECORD_VIEWED",
        "student",
        student_id,
    )
    db.commit()
    logs = (
        db.query(AccessLog)
        .filter(AccessLog.student_id == student_id)
        .order_by(AccessLog.timestamp.desc())
        .limit(100)
        .all()
    )
    embedding_count = (
        db.query(FaceEmbedding)
        .filter(FaceEmbedding.student_id == student_id)
        .count()
    )
    return {
        "student_id": student.student_id,
        "full_name": student.full_name,
        "course": student.course,
        "status": student.status,
        "created_at": student.created_at.isoformat() if student.created_at else None,
        "biometric_enrollment_count": embedding_count,
        "access_logs": [
            {
                "log_id": log.log_id,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "status_result": log.status_result,
                "confidence_distance": log.confidence_distance,
            }
            for log in logs
        ],
    }


@app.post("/api/admin/students")
def create_student(
    student: StudentCreate,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role([auth.ADMIN, auth.SUPER_ADMIN]))
):
    if db.query(Student).filter(Student.student_id == student.student_id).first():
        raise HTTPException(status_code=400, detail="Student ID already exists")
    
    new_student = Student(**student.dict())
    db.add(new_student)
    record_actor_activity(
        db,
        current,
        "STUDENT_CREATED",
        "student",
        student.student_id,
        {"full_name": student.full_name, "course": student.course, "status": student.status.value},
    )
    db.commit()
    return {"message": "Student created successfully", "student_id": new_student.student_id}

@app.patch("/api/admin/students/{student_id}")
def update_student(
    student_id: str,
    updates: StudentUpdate,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role([auth.ADMIN, auth.SUPER_ADMIN]))
):
    student = db.query(Student).filter(Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    changes = updates.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if isinstance(value, Enum):
            changes[key] = value.value
        setattr(student, key, value)

    record_actor_activity(
        db,
        current,
        "STUDENT_UPDATED",
        "student",
        student_id,
        changes,
    )
    db.commit()
    return {"message": "Student updated successfully"}


@app.delete("/api/admin/students/{student_id}")
def delete_student(
    student_id: str,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role([auth.ADMIN, auth.SUPER_ADMIN])),
):
    student = db.query(Student).filter(Student.student_id == student_id).first()
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")
    record_actor_activity(
        db,
        current,
        "STUDENT_DELETED",
        "student",
        student.student_id,
        {"full_name": student.full_name, "course": student.course},
    )
    db.delete(student)
    db.commit()
    engine_instance.reload_cache(db)
    liveness_detector.reset()
    return {"message": "Student and biometric records deleted", "student_id": student_id}

# --- Admin Operations: Biometric Enrollment ---
@app.post("/api/admin/enroll")
async def enroll_biometrics(
    student_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role([auth.ADMIN, auth.SUPER_ADMIN]))
):
    student = db.query(Student).filter(Student.student_id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student record not found")

    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    encodings = face_recognition.face_encodings(rgb_image)
    if not encodings:
        raise HTTPException(status_code=400, detail="No face detected in the uploaded image")

    # Duplicate-face check: block enrolling the same face under a different student_id
    duplicate_id = engine_instance.find_duplicate(encodings[0], exclude_student_id=student_id)
    if duplicate_id:
        raise HTTPException(
            status_code=409,
            detail=f"This face appears to already be enrolled under student ID '{duplicate_id}'"
        )

    embedding_bytes = encodings[0].astype(np.float64).tobytes()
    encrypted_embedding = encrypt_bytes(embedding_bytes)

    # Store embedding (encrypted at rest)
    face_record = FaceEmbedding(student_id=student_id, embedding_blob=encrypted_embedding)
    db.add(face_record)
    record_actor_activity(
        db,
        current,
        "BIOMETRIC_ENROLLED",
        "student",
        student_id,
        {"student_id": student_id},
    )
    db.commit()

    # Sync cache
    engine_instance.reload_cache(db)
    return {"message": f"Biometrics successfully enrolled for student {student_id}"}

# --- Admin Operations: Access Logs ---
@app.get("/api/admin/logs")
def get_logs(
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(LOG_VIEW_ROLES))
):
    logs = db.query(AccessLog).order_by(AccessLog.timestamp.desc()).limit(limit).all()
    return [
        {
            "log_id": log.log_id,
            "student_id": log.student_id,
            "status_result": log.status_result,
            "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "confidence_distance": log.confidence_distance
        }
        for log in logs
    ]


@app.get("/api/admin/activity")
def get_activity(
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role([auth.SUPER_ADMIN, auth.ADMIN])),
):
    activities = (
        db.query(ActivityLog)
        .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": item.id,
            "timestamp": item.created_at.isoformat(),
            "actor_username": item.actor_username,
            "actor_role": item.actor_role,
            "action": item.action,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "details": json.loads(item.details) if item.details else {},
        }
        for item in activities
    ]


@app.delete("/api/admin/logs")
def delete_all_logs(
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(LOG_DELETE_ROLES)),
):
    deleted = db.query(AccessLog).delete(synchronize_session=False)
    record_actor_activity(
        db,
        current,
        "ACCESS_LOGS_DELETED",
        "access_log",
        details={"count": deleted},
    )
    db.commit()
    engine_instance.last_log_times.clear()
    return {"message": "Access logs deleted", "deleted_count": deleted}


@app.delete("/api/admin/logs/{log_id}")
def delete_log(
    log_id: int,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(LOG_DELETE_ROLES)),
):
    log = db.query(AccessLog).filter(AccessLog.log_id == log_id).first()
    if log is None:
        raise HTTPException(status_code=404, detail="Access log not found")
    record_actor_activity(
        db,
        current,
        "ACCESS_LOG_DELETED",
        "access_log",
        str(log_id),
        {"student_id": log.student_id, "status_result": log.status_result},
    )
    db.delete(log)
    db.commit()
    return {"message": "Access log deleted", "log_id": log_id}

# --- RTSP camera management ---
@app.get("/api/admin/cameras")
def list_cameras(
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(CAMERA_VIEW_ROLES)),
):
    cameras = db.query(Camera).order_by(Camera.camera_name.asc()).all()
    results = [
        {
            "camera_id": camera.camera_id,
            "camera_name": camera.camera_name,
            "is_active": bool(camera.is_active),
            "status": camera.status,
            "is_selected": bool(camera.is_selected),
            "type": "rtsp",
        }
        for camera in cameras
    ]
    results.insert(
        0,
        {
            "camera_id": "webcam",
            "camera_name": "Laptop webcam (local test)",
            "is_active": True,
            "status": WEBCAM_STATUS,
            "is_selected": False,
            "type": "webcam",
        },
    )
    return results


@app.post("/api/admin/cameras")
def add_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(CAMERA_MANAGEMENT_ROLES)),
):
    if db.query(Camera).filter(Camera.camera_id == payload.camera_id).first():
        raise HTTPException(status_code=409, detail="Camera ID already exists")
    camera = Camera(
        camera_id=payload.camera_id,
        camera_name=payload.camera_name,
        encrypted_url=encrypt_text(payload.rtsp_url),
        is_active=1,
        status="OFFLINE",
    )
    db.add(camera)
    record_actor_activity(
        db,
        current,
        "CAMERA_ADDED",
        "camera",
        camera.camera_id,
        {"camera_name": camera.camera_name},
    )
    db.commit()
    return {"message": "RTSP camera registered", "camera_id": camera.camera_id}


@app.patch("/api/admin/cameras/{camera_id}")
def update_camera(
    camera_id: str,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(CAMERA_MANAGEMENT_ROLES)),
):
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    changes = {
        key: value
        for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if not changes:
        raise HTTPException(
            status_code=400,
            detail="Provide a camera name or RTSP URL to update",
        )
    if payload.camera_name is not None:
        camera.camera_name = payload.camera_name
    if payload.rtsp_url is not None:
        camera.encrypted_url = encrypt_text(payload.rtsp_url)
        camera.camera_url = ""
        camera.status = "OFFLINE"
        close_camera_streams(camera_id)
    record_actor_activity(
        db,
        current,
        "CAMERA_UPDATED",
        "camera",
        camera_id,
        {
            "camera_name": payload.camera_name,
            "rtsp_url_changed": payload.rtsp_url is not None,
        },
    )
    db.commit()
    return {"message": "Camera updated", "camera_id": camera_id}


@app.delete("/api/admin/cameras/{camera_id}")
def delete_camera(
    camera_id: str,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(CAMERA_MANAGEMENT_ROLES)),
):
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    close_camera_streams(camera_id)
    record_actor_activity(
        db,
        current,
        "CAMERA_DELETED",
        "camera",
        camera.camera_id,
        {"camera_name": camera.camera_name},
    )
    db.delete(camera)
    db.commit()
    return {"message": "Camera removed", "camera_id": camera_id}


def close_camera_streams(camera_id: str) -> None:
    with CAMERA_STATE_LOCK:
        CAMERA_GENERATIONS[camera_id] = CAMERA_GENERATIONS.get(camera_id, 0) + 1
        for stream in CAMERA_STREAMS.pop(camera_id, []):
            stream.release()


def get_camera_source(db: Session, camera_id: str):
    if camera_id == "webcam":
        return 0, None
    camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
    if camera is None or not camera.is_active:
        raise HTTPException(status_code=404, detail="Camera not found or inactive")
    return decrypt_text(camera.encrypted_url), camera


@app.post("/api/admin/cameras/{camera_id}/start")
def start_camera(
    camera_id: str,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(CAMERA_MANAGEMENT_ROLES)),
):
    global WEBCAM_STATUS
    source, camera = get_camera_source(db, camera_id)
    capture = cv2.VideoCapture(source)
    is_ready = capture.isOpened()
    if is_ready:
        is_ready, _ = capture.read()
    capture.release()

    state = "ONLINE" if is_ready else "OFFLINE"
    if camera is None:
        WEBCAM_STATUS = state
    else:
        camera.status = state
    with CAMERA_STATE_LOCK:
        CAMERA_GENERATIONS[camera_id] = CAMERA_GENERATIONS.get(camera_id, 0) + 1
    record_actor_activity(
        db,
        current,
        "CAMERA_STARTED" if is_ready else "CAMERA_START_FAILED",
        "camera",
        camera_id,
        {"camera_name": camera.camera_name if camera else "Laptop webcam"},
    )
    db.commit()
    if not is_ready:
        raise HTTPException(
            status_code=503,
            detail="Camera did not open or produce a video frame",
        )
    return {"message": "Camera started", "camera_id": camera_id, "status": state}


@app.post("/api/admin/cameras/{camera_id}/stop")
def stop_camera(
    camera_id: str,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(CAMERA_MANAGEMENT_ROLES)),
):
    global WEBCAM_STATUS
    _, camera = get_camera_source(db, camera_id)
    close_camera_streams(camera_id)
    if camera is None:
        WEBCAM_STATUS = "OFFLINE"
        camera_name = "Laptop webcam"
    else:
        camera.status = "OFFLINE"
        camera_name = camera.camera_name
    record_actor_activity(
        db,
        current,
        "CAMERA_STOPPED",
        "camera",
        camera_id,
        {"camera_name": camera_name},
    )
    db.commit()
    return {"message": "Camera stopped", "camera_id": camera_id, "status": "OFFLINE"}


@app.post("/api/admin/cameras/{camera_id}/switch")
def switch_camera(
    camera_id: str,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(CAMERA_VIEW_ROLES)),
):
    if camera_id == "webcam":
        camera_name = "Laptop webcam"
    else:
        camera = db.query(Camera).filter(Camera.camera_id == camera_id).first()
        if camera is None or not camera.is_active:
            raise HTTPException(status_code=404, detail="Camera not found or inactive")
        camera_name = camera.camera_name
    db.query(Camera).update({Camera.is_selected: 0}, synchronize_session=False)
    if camera_id != "webcam":
        camera.is_selected = 1
    record_actor_activity(
        db,
        current,
        "CAMERA_SWITCHED",
        "camera",
        camera_id,
        {"camera_name": camera_name},
    )
    db.commit()
    return {"message": "Camera selected", "camera_id": camera_id}


# --- Gate Monitoring: local webcam and registered RTSP feeds ---
def generate_camera_stream(
    camera: cv2.VideoCapture,
    camera_id: str,
    system_generation: int,
    camera_generation: int,
):
    db = SessionLocal()
    stream_lost = False
    try:
        while True:
            with SYSTEM_STATE_LOCK:
                if system_generation != SYSTEM_GENERATION:
                    break
            with CAMERA_STATE_LOCK:
                if camera_generation != CAMERA_GENERATIONS.get(camera_id, 0):
                    break
            success, frame = camera.read()
            if not success:
                stream_lost = True
                break

            with SYSTEM_STATE_LOCK:
                processed_frame = engine_instance.process_frame(frame, db)
                _, buffer = cv2.imencode('.jpg', processed_frame)
                frame_bytes = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    finally:
        camera.release()
        with CAMERA_STATE_LOCK:
            streams = CAMERA_STREAMS.get(camera_id, [])
            if camera in streams:
                streams.remove(camera)
            if not streams:
                CAMERA_STREAMS.pop(camera_id, None)
        if stream_lost:
            with SYSTEM_STATE_LOCK:
                system_generation_is_current = system_generation == SYSTEM_GENERATION
            with CAMERA_STATE_LOCK:
                generation_is_current = (
                    camera_generation == CAMERA_GENERATIONS.get(camera_id, 0)
                )
            if generation_is_current and system_generation_is_current:
                update_db = SessionLocal()
                try:
                    if camera_id == "webcam":
                        global WEBCAM_STATUS
                        if WEBCAM_STATUS == "ONLINE":
                            WEBCAM_STATUS = "OFFLINE"
                            record_activity(
                                update_db,
                                "SYSTEM",
                                "SYSTEM",
                                "CAMERA_STREAM_LOST",
                                "camera",
                                camera_id,
                            )
                            update_db.commit()
                    else:
                        camera_record = (
                            update_db.query(Camera)
                            .filter(Camera.camera_id == camera_id)
                            .first()
                        )
                        if camera_record and camera_record.status == "ONLINE":
                            camera_record.status = "OFFLINE"
                            record_activity(
                                update_db,
                                "SYSTEM",
                                "SYSTEM",
                                "CAMERA_STREAM_LOST",
                                "camera",
                                camera_id,
                                {"camera_name": camera_record.camera_name},
                            )
                            update_db.commit()
                finally:
                    update_db.close()
        db.close()

@app.get("/api/gate/video-feed")
def video_feed(
    camera_id: str = "webcam",
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role(CAMERA_VIEW_ROLES)),
):
    source, camera_record = get_camera_source(db, camera_id)
    status_value = WEBCAM_STATUS if camera_record is None else camera_record.status
    if status_value != "ONLINE":
        raise HTTPException(
            status_code=409,
            detail="Camera is stopped. An admin must start it before viewing the feed.",
        )

    camera = cv2.VideoCapture(source)
    if not camera.isOpened():
        camera.release()
        logger.error("Unable to open configured video source %s", camera_id)
        raise HTTPException(status_code=503, detail="Unable to open video source")

    with CAMERA_STATE_LOCK:
        camera_generation = CAMERA_GENERATIONS.get(camera_id, 0)
        CAMERA_STREAMS.setdefault(camera_id, []).append(camera)
    record_actor_activity(
        db,
        current,
        "CAMERA_FEED_OPENED",
        "camera",
        camera_id,
        {"camera_name": camera_record.camera_name if camera_record else "Laptop webcam"},
    )
    db.commit()
    return StreamingResponse(
        generate_camera_stream(
            camera,
            camera_id,
            SYSTEM_GENERATION,
            camera_generation,
        ),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(STATIC_DIR / "index.html")
