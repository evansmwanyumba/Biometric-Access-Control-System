import cv2
import numpy as np
import face_recognition
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .database import engine, Base, get_db
from .models import Student, FaceEmbedding, AccessLog
from .services import engine_instance

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Biometric Access Control API")

# --- Pydantic Schemas ---
class StudentCreate(BaseModel):
    student_id: str
    full_name: str
    course: str
    status: Optional[str] = "ACTIVE"

class StudentUpdate(BaseModel):
    full_name: Optional[str] = None
    course: Optional[str] = None
    status: Optional[str] = None

# --- Application Startup ---
@app.on_event("startup")
def startup_event():
    db = next(get_db())
    engine_instance.reload_cache(db)

# --- Admin Operations: Student Management ---
@app.post("/api/admin/students")
def create_student(student: StudentCreate, db: Session = Depends(get_db)):
    if db.query(Student).filter(Student.student_id == student.student_id).first():
        raise HTTPException(status_code=400, detail="Student ID already exists")
    
    new_student = Student(**student.dict())
    db.add(new_student)
    db.commit()
    return {"message": "Student created successfully", "student_id": new_student.student_id}

@app.patch("/api/admin/students/{student_id}")
def update_student(student_id: str, updates: StudentUpdate, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db)
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

    embedding_bytes = encodings[0].astype(np.float64).tobytes()
    
    # Store embedding
    face_record = FaceEmbedding(student_id=student_id, embedding_blob=embedding_bytes)
    db.add(face_record)
    db.commit()

    # Sync cache
    engine_instance.reload_cache(db)
    return {"message": f"Biometrics successfully enrolled for student {student_id}"}

# --- Admin Operations: Access Logs ---
@app.get("/api/admin/logs")
def get_logs(limit: int = 50, db: Session = Depends(get_db)):
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

# --- Gate Monitoring: Streaming Feed ---
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