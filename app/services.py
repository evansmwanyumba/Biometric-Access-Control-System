import cv2
import numpy as np
import face_recognition
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from .models import Student, FaceEmbedding, AccessLog
from .liveness import liveness_detector

# --- Matching thresholds (face_recognition distance: lower = stricter match) ---
# RECOGNITION_TOLERANCE: max distance to accept a live face as a known student at the gate.
#   face_recognition's own default is 0.6 (looser). 0.5 trades a slightly higher
#   false-reject rate for a lower false-accept rate, which is the right tradeoff
#   for access control. Tune based on real testing with your enrolled students.
RECOGNITION_TOLERANCE = 0.5

# DUPLICATE_TOLERANCE: max distance to treat a NEW enrollment photo as "the same face"
#   as an already-enrolled student. Kept stricter (lower) than RECOGNITION_TOLERANCE
#   on purpose: we want to be very confident before blocking an enrollment outright.
DUPLICATE_TOLERANCE = 0.4

# --- Detection range tuning ---
# DETECTION_SCALE: how much we shrink the frame before running face detection.
#   Smaller = faster but loses detail on small/far-away faces.
#   0.25 (old default) is aggressive and hurts far-range detection.
#   0.5 keeps 4x more pixel area, meaningfully better range, still much
#   faster than running on the full frame every time.
DETECTION_SCALE = 0.5

# UPSAMPLE_TIMES: face_recognition's own upsampling — each increment roughly
#   doubles detectable range for small/far faces, at a real speed cost.
#   1 is a reasonable middle ground for a gate camera; raise if you need to
#   catch subjects further away and can tolerate a slower feed.
UPSAMPLE_TIMES = 1

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

    def process_frame(self, frame: np.ndarray, db: Session, tolerance: float = RECOGNITION_TOLERANCE):
        """Detects faces, matches vectors, checks status, and logs access."""
        # Scale down frame for faster computer vision processing
        small_frame = cv2.resize(frame, (0, 0), fx=DETECTION_SCALE, fy=DETECTION_SCALE)
        rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

        gray_full_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        locations = face_recognition.face_locations(
            rgb_small_frame, number_of_times_to_upsample=UPSAMPLE_TIMES
        )
        encodings = face_recognition.face_encodings(rgb_small_frame, locations)

        scale_factor = int(round(1 / DETECTION_SCALE))
        for (top, right, bottom, left), face_encoding in zip(locations, encodings):
            # Upscale coordinates back to full-frame resolution — used both for
            # drawing AND for full-res liveness landmark cropping (see below)
            top, right, bottom, left = (
                top * scale_factor, right * scale_factor,
                bottom * scale_factor, left * scale_factor
            )
            
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
                    
                    # Liveness check — only recognized faces are worth checking.
                    # Uses full-res coordinates so the landmark predictor gets a
                    # high-detail crop instead of the downscaled detection frame.
                    is_live = liveness_detector.update(
                        gray_full_frame, top, right, bottom, left,
                        key=student_id
                    )

                    # Fetch authorization status
                    student = db.query(Student).filter(Student.student_id == student_id).first()
                    if student:
                        if not is_live:
                            status_result = "LIVENESS_PENDING"
                            color = (255, 255, 0)  # Cyan — waiting for blink
                            label = f"{student.full_name} [BLINK TO VERIFY]"
                        elif student.status == "ACTIVE":
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

    def find_duplicate(self, new_encoding: np.ndarray, exclude_student_id: str = None):
        """
        Checks a candidate enrollment encoding against all cached embeddings.
        Returns the matching student_id if a duplicate face is found (excluding
        the student currently being enrolled, so re-enrollment/photo updates
        for the SAME student are allowed), otherwise None.
        """
        if not self.known_encodings:
            return None

        distances = face_recognition.face_distance(self.known_encodings, new_encoding)
        for dist, matched_student_id in zip(distances, self.known_student_ids):
            if matched_student_id == exclude_student_id:
                continue
            if dist <= DUPLICATE_TOLERANCE:
                return matched_student_id
        return None

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