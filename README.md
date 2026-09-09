# Biometric Access Control System

An automated facial recognition gate access control system built with FastAPI, `face_recognition` (dlib), and OpenCV.

This repo currently contains the **backend prototype**, developed and tested locally on Kali Linux. The system is designed to be OS-independent in its final form — the backend exposes a REST API and camera stream over HTTP, and a **web-based frontend** (in progress, to be added to this repo) will be the primary interface, making the deployed system accessible from any device with a browser regardless of OS.

### Project roadmap
1. ✅ Backend prototype — API, recognition engine, local webcam feed (this stage)
2. 🔜 Web frontend — gate display UI + admin dashboard
3. 🔜 Iterate on accuracy, performance, and auth/security hardening
4. 🔜 Deploy to a server
5. 🔜 Integrate with dedicated security cameras (replacing local webcam input)
6. 🔜 Full production deployment

Currently running locally against a laptop webcam purely for development and testing purposes.

## Features

- Live camera feed with real-time face detection and recognition overlay
- Student enrollment via uploaded photo (stored as face embeddings, not raw images)
- SQLite-backed student records and access logs
- REST API for admin operations (student management, enrollment, log retrieval)
- MJPEG streaming endpoint for the gate camera feed

## Tech Stack

- **OS:** Kali Linux
- **Language:** Python 3.14
- **Backend:** FastAPI + Uvicorn
- **Database:** SQLite with SQLAlchemy ORM
- **Biometric Engine:** `face_recognition` (built on `dlib`)
- **Computer Vision:** OpenCV

## Project Structure

```
FacialRec/
├── app/
│   ├── database.py      # SQLAlchemy engine/session setup
│   ├── main.py           # FastAPI routes
│   ├── models.py         # ORM models (Student, FaceEmbedding, AccessLog)
│   └── services.py       # Recognition engine, frame processing, caching
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

### 4. Build `dlib` and install `face_recognition_models`

These are not pulled in automatically via `requirements.txt` since they were built/installed manually for this environment:

```bash
git clone https://github.com/davisking/dlib.git
cd dlib && python setup.py install && cd ..

# face_recognition_models
pip install --break-system-packages git+https://github.com/ageitgey/face_recognition_models
```

### 5. Run the server

```bash
uvicorn app.main:app --reload
```

API docs available at `http://127.0.0.1:8000/docs`.

## API Overview

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/admin/students` | Create a student record |
| PATCH | `/api/admin/students/{student_id}` | Update a student record |
| POST | `/api/admin/enroll` | Enroll biometrics (photo → face embedding) for a student |
| GET | `/api/admin/logs` | Retrieve recent access logs |
| GET | `/api/gate/video-feed` | Live MJPEG stream with recognition overlay |

**Note:** `/api/gate/video-feed` is a continuous MJPEG stream and will not render properly in Swagger UI (`/docs`) — it waits indefinitely for a response that never completes. Test it with an `<img>` tag in an HTML page, or with `curl --output`.

## Data & Privacy

- Face data is stored as numeric embeddings (vectors), not raw photos, once enrollment completes.
- The SQLite database (`*.db`) and any locally used test images are excluded from version control via `.gitignore`.
- This system is intended for local, offline use. If deployed beyond a local/testing environment, review data retention and consent practices for biometric data in your jurisdiction before production use.

## Known Limitations / To Do

- Recognition runs on CPU (`hog` model); performance depends on hardware.
- No authentication/authorization on admin endpoints yet — required before any deployment beyond local testing.
- No web frontend yet — currently validated using a minimal local test page (`<img>` tag against the MJPEG feed). A full web-based gate display and admin dashboard are in progress and will be added to this repo.
- Input is a local laptop webcam for now; production deployment will swap this for dedicated security camera feeds (e.g. RTSP streams).
- Not yet deployed to a server — currently local-only for development.

## License

_###_
