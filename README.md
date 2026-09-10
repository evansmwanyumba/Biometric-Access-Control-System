# Biometric Access Control System

An automated facial recognition gate access control system built with FastAPI, `face_recognition` (dlib), and OpenCV.

This repo currently contains the **backend prototype**, developed and tested locally on Kali Linux. The system is designed to be OS-independent in its final form — the backend exposes a REST API and camera stream over HTTP, and a **web-based frontend** (in progress, to be added to this repo) will be the primary interface, making the deployed system accessible from any device with a browser regardless of OS.

### Project roadmap

```text
🔐 1. Backend security                          ✅ COMPLETE
  ├── Authentication (JWT)                      ✅
  ├── RBAC / permissions (4 roles)               ✅
  ├── Input validation                          ✅
  ├── Secure enrollment                         ✅
  ├── API authorization                         ✅
  ├── Rate limiting                             ✅
  └── Secure error handling                     ✅

🧬 2. Biometric security                        ✅ COMPLETE
  ├── Liveness detection (blink/EAR)            ✅
  ├── Anti-spoofing (static image rejection)    ✅
  ├── Threshold testing                         ✅
  └── Duplicate-face detection                  ✅

🗄️ 3. Database security                         🔶 IN PROGRESS
  ├── Constraints                               ✅
  ├── Proper relationships (FK + cascade rules) ✅
  ├── Sensitive-data protection (encryption)    ⬜
  └── Audit integrity (tamper-resistant logs)   ⬜

🌐 4. Frontend                                  ⬜ NOT STARTED
  ├── Admin login
  ├── Dashboard
  ├── Student management
  ├── Enrollment
  └── Access logs

🛡️ 5. Security testing                          ⬜ NOT STARTED
  ├── API attacks
  ├── Authentication bypass
  ├── Privilege escalation
  ├── Spoofing
  └── Input/API abuse

  ↓
🚀 Deploy to server → integrate dedicated security cameras → full production deployment
```

Currently running locally against a laptop webcam purely for development and testing purposes.

## Features

- JWT authentication with role-based access control (`SUPER_ADMIN`, `ADMIN`, `SECURITY_OFFICER`, `GATE_DEVICE`)
- Rate-limited login endpoint (brute-force protection)
- Strict input validation on all admin endpoints (enums, length/format constraints, password strength)
- Global exception handling — no internal details leaked to clients on unexpected errors
- Live camera feed with real-time face detection and recognition overlay
- Session-based liveness detection (blink/EAR) — rejects static photos held up to the camera
- Duplicate-face detection at enrollment — blocks the same face being enrolled under multiple IDs
- Tuned, documented recognition thresholds and detection range (works across close and gate-realistic distances)
- Database-level constraints and foreign key enforcement (not just application-level validation)
- SQLite-backed student records and access logs
- REST API for admin operations (student management, enrollment, log retrieval, admin user management)
- MJPEG streaming endpoint for the gate camera feed

## Tech Stack

- **OS:** Kali Linux
- **Language:** Python 3.14
- **Backend:** FastAPI + Uvicorn
- **Database:** SQLite with SQLAlchemy ORM
- **Biometric Engine:** `face_recognition` (built on `dlib`)
- **Computer Vision:** OpenCV
- **Auth:** `python-jose` (JWT), `bcrypt` (password hashing)
- **Rate Limiting:** `slowapi`

## Project Structure

```
FacialRec/
├── app/
│   ├── auth.py            # JWT creation/validation, password hashing, role-checking dependency
│   ├── database.py        # SQLAlchemy engine/session setup, SQLite FK enforcement
│   ├── liveness.py         # Blink/EAR-based liveness detection
│   ├── main.py             # FastAPI routes
│   ├── models.py           # ORM models (Student, FaceEmbedding, AccessLog, AdminUser)
│   └── services.py         # Recognition engine, frame processing, caching
├── seed_admin.py           # One-time script to bootstrap the first SUPER_ADMIN account
├── migrate_db.py           # Schema migration helper (backs up + rebuilds local_gate.db)
├── requirements.txt
└── README.md
```

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/evansmwanyumba/Biometric-Access-Control-System.git
cd Biometric-Access-Control-System
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install --break-system-packages -r requirements.txt
```

> **Note on `setuptools`:** `pkg_resources` was removed in `setuptools>=82`, which breaks the unmaintained `face_recognition_models` package. This repo pins `setuptools<82` to work around it.

> **Note on `bcrypt`:** newer `bcrypt` releases removed an attribute that older auth tooling checks for. This repo pins `bcrypt<4.1` for compatibility.

### 4. Build `dlib` and install `face_recognition_models`

These are not pulled in automatically via `requirements.txt` since they were built/installed manually for this environment:

```bash
# dlib — build from source if a prebuilt wheel isn't available for your Python version
git clone https://github.com/davisking/dlib.git
cd dlib && python setup.py install && cd ..

# face_recognition_models
pip install --break-system-packages git+https://github.com/ageitgey/face_recognition_models
```

### 5. Configure environment variables

Create a `.env` file in the project root (never committed — already in `.gitignore`):

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

```
SECRET_KEY=<paste the generated value here>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
```

`SECRET_KEY` signs every JWT this system issues — anyone with it could forge admin tokens. Keep it out of version control and treat it like any other production secret.

### 6. Bootstrap your first admin account

There's no way to create admin users through the API until one exists (`POST /api/admin/users` requires `SUPER_ADMIN`). Run this once:

```bash
python3 seed_admin.py
```

Follow the prompts to set a username and password for your first `SUPER_ADMIN`.

### 7. Run the server

```bash
uvicorn app.main:app --reload
```

API docs available at `http://127.0.0.1:8000/docs`.

## API Overview

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| POST | `/api/admin/login` | None (rate-limited: 5/min) | Log in, returns a JWT |
| POST | `/api/admin/users` | `SUPER_ADMIN` | Create a new admin/officer/device account |
| POST | `/api/admin/students` | `ADMIN`, `SUPER_ADMIN` | Create a student record |
| PATCH | `/api/admin/students/{student_id}` | `ADMIN`, `SUPER_ADMIN` | Update a student record |
| POST | `/api/admin/enroll` | `ADMIN`, `SUPER_ADMIN` | Enroll biometrics (photo → face embedding) for a student |
| GET | `/api/admin/logs` | `ADMIN`, `SUPER_ADMIN`, `SECURITY_OFFICER` | Retrieve recent access logs |
| GET | `/api/gate/video-feed` | None (local network trust) | Live MJPEG stream with recognition + liveness overlay |

**Note:** `/api/gate/video-feed` is a continuous MJPEG stream and will not render properly in Swagger UI (`/docs`) — it waits indefinitely for a response that never completes. Test it with an `<img>` tag in an HTML page, or with `curl --output`.

## How Recognition Works

1. Each frame from the camera is scanned for faces (detection runs on a downscaled copy for speed, with upsampling tuned for gate-realistic distances).
2. Detected faces are compared against cached embeddings loaded from the database (`RECOGNITION_TOLERANCE`, tuned stricter than `face_recognition`'s own default to favor fewer false accepts).
3. A recognized face must also pass **liveness verification** — a detected blink (via eye-aspect-ratio on dlib's 68-point landmarks) within the session window — before access is granted. This blocks the most common spoofing attempt (a printed photo or static image held up to the camera). It does **not** defend against a video replay of a real blinking face; that would require texture/depth analysis, which is a future enhancement, not currently implemented.
4. At enrollment time, new faces are checked against all existing embeddings (`DUPLICATE_TOLERANCE`) to prevent the same face being enrolled under multiple student IDs.
5. All tuning constants (`RECOGNITION_TOLERANCE`, `DUPLICATE_TOLERANCE`, `DETECTION_SCALE`, `UPSAMPLE_TIMES`, `EAR_THRESHOLD`, `EAR_CONSEC_FRAMES`, `LIVENESS_WINDOW`) live in `app/services.py` and `app/liveness.py` and are documented inline — expect to retune these once real camera hardware and mounting position are decided.

## Data & Privacy

- Face data is stored as numeric embeddings (vectors), not raw photos, once enrollment completes.
- **Embeddings are currently stored unencrypted at rest** in SQLite — encryption of this column is a planned, not-yet-implemented item (see roadmap above).
- The SQLite database (`*.db`), backup files, and any locally used test images are excluded from version control via `.gitignore`.
- This system is intended for local, offline use during development. If deployed beyond a local/testing environment, review data retention, encryption, and consent practices for biometric data in your jurisdiction before production use.

## Known Limitations / To Do

- Face embeddings are not yet encrypted at rest.
- Access logs are not yet tamper-resistant at the database level (no DB-level protection against direct edit/delete, only application-level).
- Liveness detection covers static-image spoofing, not video replay attacks.
- Recognition runs on CPU (`hog` model); performance depends on hardware.
- No web frontend yet — currently validated using a minimal local test page (`<img>` tag against the MJPEG feed). A full web-based gate display and admin dashboard are in progress and will be added to this repo.
- Input is a local laptop webcam for now; production deployment will swap this for dedicated security camera feeds (e.g. RTSP streams).
- Not yet deployed to a server — currently local-only for development.
- No formal security testing (penetration testing, auth bypass attempts) has been performed yet.

## License

_Add a license if you plan to make this repository public._
