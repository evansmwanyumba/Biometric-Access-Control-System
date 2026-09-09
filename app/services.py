import cv2
import numpy as np
import face_recognition
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import Student, FaceEmbedding, AccessLog

class RecognitionEngine:
    def __init__(self):
        self.known_encodings = []
        self.known_student_ids = []
        self.last_log_times = {}  # Anti-spam log debouncer: {student_id: datetime}
        self.log_cooldown = timedelta(seconds=5)

    def reload_cache(self, db: Session):
        """Loads face embeddings from SQLite into memory for fast matching."""
        self.known_encodings.clear()
        self.known_student_ids.clear()
        
        embeddings = db.query(FaceEmbedding).all()
        for record in embeddings:
            vector = np.frombuffer(record.embedding_blob, dtype=np.float64)
            self.known_encodings.append(vector)
            self.known_student_ids.append(record.student_id)

    def process_frame(self, frame: np.ndarray, db: Session, tolerance: float = 0.5):
        """Detects faces, matches vectors, checks status, and logs access."""
        # Scale down frame for faster computer vision processing
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

        locations = face_recognition.face_locations(rgb_small_frame)
        encodings = face_recognition.face_encodings(rgb_small_frame, locations)

        for (top, right, bottom, left), face_encoding in zip(locations, encodings):
            # Upscale coordinates back to original size
            top, right, bottom, left = top * 4, right * 4, bottom * 4, left * 4
            
            student_id = None
            status_result = "UNRECOGNIZED"
            min_dist = None
            color = (0, 165, 255)  # Orange for unknown
            label = "UNRECOGNIZED"

            if self.known_encodings:
                distances = face_recognition.face_distance(self.known_encodings, face_encoding)
                best_match_idx = np.argmin(distances)
                
                if distances[best_match_idx] <= tolerance:
                    min_dist = float(distances[best_match_idx])
                    student_id = self.known_student_ids[best_match_idx]
                    
                    # Fetch authorization status
                    student = db.query(Student).filter(Student.student_id == student_id).first()
                    if student:
                        if student.status == "ACTIVE":
                            status_result = "GRANTED"
                            color = (0, 255, 0)  # Green
                            label = f"{student.full_name} [GRANTED]"
                        else:
                            status_result = f"DENIED_{student.status}"
                            color = (0, 0, 255)  # Red
                            label = f"{student.full_name} [{student.status}]"

            # Debounced logging
            self._log_access(db, student_id, status_result, min_dist)

            # Draw visual bounding box and label
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
            cv2.rectangle(frame, (left, bottom - 35), (right, bottom), color, cv2.FILLED)
            cv2.putText(frame, label, (left + 6, bottom - 6), cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)

        return frame

    def _log_access(self, db: Session, student_id: str, status_result: str, distance: float):
        now = datetime.utcnow()
        key = student_id or "UNKNOWN"
        
        if key in self.last_log_times and (now - self.last_log_times[key]) < self.log_cooldown:
            return  # Skip duplicate logs during cooldown period

        self.last_log_times[key] = now
        log_entry = AccessLog(
            student_id=student_id,
            status_result=status_result,
            confidence_distance=distance
        )
        db.add(log_entry)
        db.commit()

engine_instance = RecognitionEngine()