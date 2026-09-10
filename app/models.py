from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, LargeBinary, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base

class Student(Base):
    __tablename__ = "students"

    student_id = Column(String, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    course = Column(String, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE")  # ACTIVE, SUSPENDED, INACTIVE
    created_at = Column(DateTime, default=datetime.utcnow)

    embeddings = relationship("FaceEmbedding", back_populates="student", cascade="all, delete-orphan")
    logs = relationship("AccessLog", back_populates="student")

class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    student_id = Column(String, ForeignKey("students.student_id"), nullable=False)
    embedding_blob = Column(LargeBinary, nullable=False)

    student = relationship("Student", back_populates="embeddings")

class AccessLog(Base):
    __tablename__ = "access_logs"

    log_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    student_id = Column(String, ForeignKey("students.student_id"), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status_result = Column(String, nullable=False)  # GRANTED, DENIED_SUSPENDED, UNRECOGNIZED
    confidence_distance = Column(Float, nullable=True)

    student = relationship("Student", back_populates="logs")
class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # SUPER_ADMIN, ADMIN, SECURITY_OFFICER, GATE_DEVICE
    is_active = Column(Integer, default=1)  # 1 = active, 0 = disabled
    created_at = Column(DateTime, default=datetime.utcnow)
