from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, LargeBinary, DateTime, ForeignKey, CheckConstraint, Text
from sqlalchemy.orm import relationship
from .database import Base

class Student(Base):
    __tablename__ = "students"

    student_id = Column(String, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    course = Column(String, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE")  # ACTIVE, SUSPENDED, INACTIVE
    created_at = Column(DateTime, default=datetime.utcnow)

    embeddings = relationship(
        "FaceEmbedding", back_populates="student", cascade="all, delete-orphan"
    )
    logs = relationship("AccessLog", back_populates="student")

    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'SUSPENDED', 'INACTIVE')", name="ck_student_status"),
    )

class FaceEmbedding(Base):
    __tablename__ = "face_embeddings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    student_id = Column(
        String, ForeignKey("students.student_id", ondelete="CASCADE"), nullable=False
    )
    embedding_blob = Column(LargeBinary, nullable=False)

    student = relationship("Student", back_populates="embeddings")

class AccessLog(Base):
    __tablename__ = "access_logs"

    log_id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    student_id = Column(
        String, ForeignKey("students.student_id", ondelete="SET NULL"), nullable=True
    )
    timestamp = Column(DateTime, default=datetime.utcnow)
    status_result = Column(String, nullable=False)  # GRANTED, DENIED_*, UNRECOGNIZED, LIVENESS_PENDING
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
    token_version = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "role IN ('SUPER_ADMIN', 'ADMIN', 'SECURITY_OFFICER', 'GATE_PERSONNEL', 'GATE_DEVICE')",
            name="ck_admin_role"
        ),
        CheckConstraint("is_active IN (0, 1)", name="ck_admin_is_active"),
    )


class Camera(Base):
    __tablename__ = "cameras"

    camera_id = Column(String, primary_key=True, index=True)
    camera_name = Column(String, nullable=False)
    camera_type = Column(String, nullable=False, default="cctv")
    location = Column(String, nullable=False, default="")
    ip_address = Column(String, nullable=False, default="")
    status = Column(String, nullable=False, default="OFFLINE")
    is_selected = Column(Integer, nullable=False, default=0)
    camera_url = Column(String, nullable=False, default="")
    encrypted_url = Column(LargeBinary, nullable=False)
    is_active = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("camera_type IN ('cctv')", name="ck_camera_type"),
        CheckConstraint(
            "status IN ('ONLINE', 'OFFLINE', 'MAINTENANCE')",
            name="ck_camera_status",
        ),
        CheckConstraint("is_active IN (0, 1)", name="ck_camera_is_active"),
    )


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    actor_username = Column(String, nullable=False, index=True)
    actor_role = Column(String, nullable=False)
    action = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
