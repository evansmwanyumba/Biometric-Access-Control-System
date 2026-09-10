import dlib
import numpy as np
import face_recognition_models
from datetime import datetime, timedelta

# --- Landmark indices for the 68-point model ---
LEFT_EYE_IDX = list(range(42, 48))
RIGHT_EYE_IDX = list(range(36, 42))

# --- Tuning constants ---
EAR_THRESHOLD = 0.21          # below this, eye is considered "closed"
EAR_CONSEC_FRAMES = 2         # how many consecutive closed-eye frames count as a real blink
                               # (filters out single-frame detection noise, not a genuine blink)
LIVENESS_WINDOW = timedelta(seconds=60)  # how long a detected blink keeps a session "live"


def _euclidean(p1, p2):
    return float(np.linalg.norm(np.array(p1) - np.array(p2)))


def eye_aspect_ratio(eye_points):
    """
    eye_points: 6 (x, y) landmark points for one eye, in dlib's standard order.
    Returns a ratio that drops sharply when the eye closes.
    """
    A = _euclidean(eye_points[1], eye_points[5])
    B = _euclidean(eye_points[2], eye_points[4])
    C = _euclidean(eye_points[0], eye_points[3])
    if C == 0:
        return 0.0
    return (A + B) / (2.0 * C)


class LivenessDetector:
    """
    Session-based blink liveness check. Once a blink is detected for a given
    tracking key (we use student_id, since liveness only matters once a face
    has already matched a known encoding), that key is considered "live" for
    LIVENESS_WINDOW. This is a lightweight anti-spoofing measure against
    static photos — it does NOT defend against a video replay of a blinking
    face, which would need stronger measures (texture/depth analysis).
    """

    def __init__(self):
        model_path = face_recognition_models.pose_predictor_model_location()
        self.predictor = dlib.shape_predictor(model_path)

        self._closed_frame_counts = {}   # key -> consecutive closed-eye frame count
        self._live_until = {}            # key -> datetime the "live" status expires

    def _landmarks_for_crop(self, gray_crop):
        h, w = gray_crop.shape[:2]
        rect = dlib.rectangle(left=0, top=0, right=w, bottom=h)
        shape = self.predictor(gray_crop, rect)
        return [(shape.part(i).x, shape.part(i).y) for i in range(68)]

    def update(self, gray_full_frame, top, right, bottom, left, key: str) -> bool:
        """
        Call once per frame for a given detected face. `top/right/bottom/left`
        must be FULL-RESOLUTION coordinates (not the downscaled detection
        frame) — we crop the face out of the full-res frame here so the
        landmark predictor has enough detail for a reliable EAR signal,
        even though face detection itself runs on a downscaled frame for speed.
        """
        h, w = gray_full_frame.shape[:2]
        pad = 20  # small margin so eye landmarks near the box edge aren't clipped
        crop_top = max(0, top - pad)
        crop_left = max(0, left - pad)
        crop_bottom = min(h, bottom + pad)
        crop_right = min(w, right + pad)

        gray_crop = gray_full_frame[crop_top:crop_bottom, crop_left:crop_right]
        if gray_crop.size == 0:
            return self.is_live(key)

        landmarks = self._landmarks_for_crop(gray_crop)

        left_eye = [landmarks[i] for i in LEFT_EYE_IDX]
        right_eye = [landmarks[i] for i in RIGHT_EYE_IDX]
        avg_ear = (eye_aspect_ratio(left_eye) + eye_aspect_ratio(right_eye)) / 2.0

        if avg_ear < EAR_THRESHOLD:
            self._closed_frame_counts[key] = self._closed_frame_counts.get(key, 0) + 1
        else:
            if self._closed_frame_counts.get(key, 0) >= EAR_CONSEC_FRAMES:
                # Eyes just reopened after being closed long enough — count as a blink
                self._live_until[key] = datetime.utcnow() + LIVENESS_WINDOW
            self._closed_frame_counts[key] = 0

        return self.is_live(key)

    def is_live(self, key: str) -> bool:
        expiry = self._live_until.get(key)
        return expiry is not None and datetime.utcnow() < expiry


liveness_detector = LivenessDetector()
