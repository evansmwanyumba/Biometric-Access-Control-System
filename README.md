# Biometric Access Control System

An automated facial recognition gate access control system built with FastAPI, `face_recognition` (dlib), and OpenCV.

The system includes a browser dashboard served at `http://127.0.0.1:8000/`, alongside its FastAPI API.

### Project roadmap

```text
🔐 1. Backend security                          ✅ COMPLETE
  ├── Authentication (JWT)                      ✅
  ├── RBAC / permissions (5 roles)               ✅
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
  ├── Sensitive-data protection (encryption)    ✅
  └── Audit integrity (tamper-resistant logs)   ⬜

🌐 4. Frontend                                  ✅ LOCAL DASHBOARD
  ├── Admin login and role-based dashboard
  ├── Camera feeds and RTSP setup
  ├── Student management and enrollment
  └── Access logs and administration

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

- JWT authentication with role-based access control (`SUPER_ADMIN`, `ADMIN`, `SECURITY_OFFICER`, `GATE_PERSONNEL`, `GATE_DEVICE`)
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
│   ├── main.py             # FastAPI routes and compatibility migrations
│   ├── models.py           # ORM models (Student, FaceEmbedding, AccessLog, AdminUser)
│   ├── services.py         # Recognition engine, frame processing, caching
│   └── static/              # Local dashboard assets
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
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```
SECRET_KEY=<paste the generated value here>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
ENCRYPTION_KEY=<paste the generated Fernet key here>
```

`SECRET_KEY` signs every JWT this system issues — anyone with it could forge admin tokens. `ENCRYPTION_KEY` protects stored face embeddings and RTSP URLs; losing it makes those encrypted values unrecoverable. Keep both out of version control and treat them as production secrets.

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

### Dashboard and role permissions

Visit `http://127.0.0.1:8000/` to sign in. Create the first `SUPER_ADMIN` using `python seed_admin.py`.

| Role | Permissions |
|---|---|
| `SUPER_ADMIN` | Full system access, including account/camera/student/log management, audit history, and the full-system wipe |
| `ADMIN` | Manage students and biometrics, camera lifecycle, view/delete access logs, and manage gate personnel/device accounts |
| `SECURITY_OFFICER` | View access logs and camera feeds/status |
| `GATE_PERSONNEL` | View logs and switch between camera feeds |
| `GATE_DEVICE` | View and switch camera feeds only |

Admins cannot create or delete admin accounts. Deleting the account currently signed in is blocked to prevent accidentally stranding the system. The full-system wipe is only available to super admins; it deletes all database rows, including every account, and requires typing `WIPE EVERYTHING`. Afterward, use `python seed_admin.py` to create a new super admin.

RTSP cameras can be registered from **Cameras & status** by pasting the camera/NVR's RTSP URL. Camera URLs are encrypted in the database and are not returned by the API. Use the per-camera controls to start, stop, edit, or delete a stream; starting probes that the camera is reachable and producing frames. The laptop webcam is listed as the local test feed and can be controlled the same way.

Admins and super admins can click any row in **Students** to inspect the record, biometric enrollment count, and recent access history, then modify or permanently delete it. **Activity history** records the actor, role, action, target, and safe details for account, student, camera, authentication, enrollment, feed, and access-log changes. Activity history is append-only in the dashboard; a full-system wipe deletes it together with every other database row.

Every signed-in account has a **My account** page to change its own username, password, or both. The current password is required to confirm a change. Saving a change renews the current browser session and invalidates all previously issued tokens for that account, so other sessions must sign in again.

## API Overview

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| POST | `/api/admin/login` | None (rate-limited: 5/min) | Log in, returns a JWT |
| PATCH | `/api/admin/account` | Any authenticated account | Change own username/password; invalidates prior sessions |
| GET/POST | `/api/admin/users` | `SUPER_ADMIN`, `ADMIN` | List/create accounts; admins can manage gate accounts only |
| DELETE | `/api/admin/users/{username}` | `SUPER_ADMIN`, `ADMIN` | Delete an account subject to role limits |
| DELETE | `/api/admin/system/wipe?confirmation=WIPE%20EVERYTHING` | `SUPER_ADMIN` | Permanently clear every database table and account |
| POST | `/api/admin/cameras` | `SUPER_ADMIN`, `ADMIN` | Register an encrypted RTSP camera URL |
| PATCH/DELETE | `/api/admin/cameras/{camera_id}` | `SUPER_ADMIN`, `ADMIN` | Modify or delete a camera |
| POST | `/api/admin/cameras/{camera_id}/start` | `SUPER_ADMIN`, `ADMIN` | Probe and start a camera |
| POST | `/api/admin/cameras/{camera_id}/stop` | `SUPER_ADMIN`, `ADMIN` | Stop a camera and close its active feed streams |
| POST | `/api/admin/cameras/{camera_id}/switch` | Authenticated camera roles | Select a camera |
| GET | `/api/admin/activity` | `SUPER_ADMIN`, `ADMIN` | Read the append-only activity audit history |
| GET/PATCH/DELETE | `/api/admin/students/{student_id}` | `SUPER_ADMIN`, `ADMIN` | Read, modify, or permanently delete one student record |
| DELETE | `/api/admin/logs/{log_id}` | `SUPER_ADMIN`, `ADMIN` | Delete one access log |
| DELETE | `/api/admin/logs` | `SUPER_ADMIN`, `ADMIN` | Delete all access logs |
| POST | `/api/admin/students` | `ADMIN`, `SUPER_ADMIN` | Create a student record |
| PATCH | `/api/admin/students/{student_id}` | `ADMIN`, `SUPER_ADMIN` | Update a student record |
| POST | `/api/admin/enroll` | `ADMIN`, `SUPER_ADMIN` | Enroll biometrics (photo → face embedding) for a student |
| GET | `/api/admin/logs` | `ADMIN`, `SUPER_ADMIN`, `SECURITY_OFFICER`, `GATE_PERSONNEL` | Retrieve recent access logs |
| GET | `/api/gate/video-feed` | Authenticated camera roles | Live webcam or registered RTSP MJPEG stream with recognition + liveness overlay |

**Note:** `/api/gate/video-feed` is a continuous MJPEG stream and will not render properly in Swagger UI (`/docs`) — it waits indefinitely for a response that never completes. Test it with an `<img>` tag in an HTML page, or with `curl --output`.

## How Recognition Works

1. Each frame from the camera is scanned for faces (detection runs on a downscaled copy for speed, with upsampling tuned for gate-realistic distances).
2. Detected faces are compared against cached embeddings loaded from the database (`RECOGNITION_TOLERANCE`, tuned stricter than `face_recognition`'s own default to favor fewer false accepts).
3. A recognized face must also pass **liveness verification** — a detected blink (via eye-aspect-ratio on dlib's 68-point landmarks) within the session window — before access is granted. This blocks the most common spoofing attempt (a printed photo or static image held up to the camera). It does **not** defend against a video replay of a real blinking face; that would require texture/depth analysis, which is a future enhancement, not currently implemented.
4. At enrollment time, new faces are checked against all existing embeddings (`DUPLICATE_TOLERANCE`) to prevent the same face being enrolled under multiple student IDs.
5. All tuning constants (`RECOGNITION_TOLERANCE`, `DUPLICATE_TOLERANCE`, `DETECTION_SCALE`, `UPSAMPLE_TIMES`, `EAR_THRESHOLD`, `EAR_CONSEC_FRAMES`, `LIVENESS_WINDOW`) live in `app/services.py` and `app/liveness.py` and are documented inline — expect to retune these once real camera hardware and mounting position are decided.

## Data & Privacy

- Face data is stored as encrypted numeric embeddings (vectors), not raw photos, once enrollment completes. Registered RTSP URLs are encrypted as well.
- The SQLite database (`*.db`), backup files, and any locally used test images are excluded from version control via `.gitignore`.
- This system is intended for local, offline use during development. If deployed beyond a local/testing environment, review data retention, encryption, and consent practices for biometric data in your jurisdiction before production use.

## Known Limitations / To Do

- Access logs are not yet tamper-resistant at the database level (no DB-level protection against direct edit/delete, only application-level).
- Liveness detection covers static-image spoofing, not video replay attacks.
- Recognition runs on CPU (`hog` model); performance depends on hardware.
- Detection uses full-resolution frames and upsampling for smaller faces, which increases CPU cost. Software cannot replace appropriate CCTV resolution, optical zoom, mounting position, lighting, or a clear view of faces; validate recognition at the intended distance before relying on it for access decisions.
- RTSP support depends on OpenCV's video backend and the camera/NVR's exact stream path and network configuration.
- Not yet deployed to a server — currently local-only for development.
- No formal security testing (penetration testing, auth bypass attempts) has been performed yet.

## License

_Add a license if you plan to make this repository public._
