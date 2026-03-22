# AiDetect — AI-Powered Invoice Fraud & Duplicate Detection Engine

> An automated "firewall" system for finance teams that detects duplicate, forged, or manipulated invoices using OCR, machine learning, and forensic analysis.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11-green.svg)
![React](https://img.shields.io/badge/react-18-blue.svg)

## 🏗️ Architecture

- **Frontend**: React + Vite (premium finance dashboard)
- **Backend**: FastAPI (REST API + WebSocket)
- **Task Queue**: Celery + Redis (async processing)
- **Database**: PostgreSQL (structured storage)
- **Vector Store**: FAISS (duplicate fingerprint matching)
- **OCR**: Tesseract (text extraction)
- **ML**: Isolation Forest + Autoencoder (anomaly detection)
- **Storage**: MinIO (S3-compatible file storage)

## 🚀 Quick Start

### With Docker (Recommended)
```bash
# Clone and start
cp .env.example .env
docker-compose up --build
```

### Development (Without Docker)

**Backend:**
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## 📍 Access Points

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| MinIO Console | http://localhost:9001 |

## 🛡️ Core Features

1. **Invoice OCR** - Tesseract-powered extraction of vendor, amounts, dates
2. **Forgery Detection** - ELA, metadata analysis, copy-paste detection
3. **Duplicate Detection** - SHA-256 hash, perceptual hash, fuzzy matching, FAISS vectors
4. **Anomaly Detection** - Isolation Forest + Autoencoder ML models
5. **Risk Scoring** - Weighted composite score with 4-tier classification
6. **Audit Dashboard** - Review, approve, reject with full evidence
7. **Encryption** - Fernet symmetric encryption at rest
8. **Audit Logging** - Full action trail for compliance
