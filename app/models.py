from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, LargeBinary, DateTime, ForeignKey, CheckConstraint
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

    __table_args__ = (
        CheckConstraint(
            "role IN ('SUPER_ADMIN', 'ADMIN', 'SECURITY_OFFICER', 'GATE_DEVICE')",
            name="ck_admin_role"
        ),
        CheckConstraint("is_active IN (0, 1)", name="ck_admin_is_active"),
    )
