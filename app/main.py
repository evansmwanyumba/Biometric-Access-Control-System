import cv2
import numpy as np
import face_recognition
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel
from sqlalchemy.orm import Session

import logging
import traceback

from .database import engine, Base, get_db
from .models import Student, FaceEmbedding, AccessLog, AdminUser
from .services import engine_instance
from .crypto_utils import encrypt_bytes
from . import auth
from .auth import require_role, get_current_admin, CurrentAdmin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("facialrec")

Base.metadata.create_all(bind=engine)

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
import re
from enum import Enum
from pydantic import BaseModel, field_validator, Field

class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"

class AdminRole(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    SECURITY_OFFICER = "SECURITY_OFFICER"
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

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

# --- Application Startup ---
@app.on_event("startup")
def startup_event():
    db = next(get_db())
    engine_instance.reload_cache(db)

# --- Auth ---
@app.post("/api/admin/login", response_model=Token)
@limiter.limit("5/minute")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(AdminUser.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    token = auth.create_access_token(data={"sub": user.username, "role": user.role})
    return Token(access_token=token)

# --- Admin Operations: Admin User Management (SUPER_ADMIN only) ---
@app.post("/api/admin/users")
def create_admin_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role([auth.SUPER_ADMIN]))
):
    if db.query(AdminUser).filter(AdminUser.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")

    new_user = AdminUser(
        username=payload.username,
        hashed_password=auth.hash_password(payload.password),
        role=payload.role.value,
        is_active=1
    )
    db.add(new_user)
    db.commit()
    return {"message": f"Admin user '{payload.username}' created with role {payload.role.value}"}

# --- Admin Operations: Student Management ---
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
    
    for key, value in updates.dict(exclude_unset=True).items():
        setattr(student, key, value)
        
    db.commit()
    return {"message": "Student updated successfully"}

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
    db.commit()

    # Sync cache
    engine_instance.reload_cache(db)
    return {"message": f"Biometrics successfully enrolled for student {student_id}"}

# --- Admin Operations: Access Logs ---
@app.get("/api/admin/logs")
def get_logs(
    limit: int = 50,
    db: Session = Depends(get_db),
    current: CurrentAdmin = Depends(require_role([auth.ADMIN, auth.SUPER_ADMIN, auth.SECURITY_OFFICER]))
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

# --- Gate Monitoring: Streaming Feed (open on local network for now) ---
def generate_camera_stream():
    camera = cv2.VideoCapture(0)
    db = next(get_db())
    try:
        while True:
            success, frame = camera.read()
            if not success:
                break
            
            # Process recognition over frame
            processed_frame = engine_instance.process_frame(frame, db)
            
            # Encode frame to JPEG
            _, buffer = cv2.imencode('.jpg', processed_frame)
            frame_bytes = buffer.tobytes()
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    finally:
        camera.release()

@app.get("/api/gate/video-feed")
def video_feed():
    return StreamingResponse(
        generate_camera_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )
