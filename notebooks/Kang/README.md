# 모의면접 감정 분석 시스템

## 📁 구조
```
interview-emotion/
├── backend/
│   ├── main.py           # FastAPI + DeepFace 서버
│   └── requirements.txt  # 파이썬 패키지
└── frontend/
    └── index.html        # 웹 클라이언트
```

## 🚀 설치 & 실행

### 1. 파이썬 가상환경 생성
```bash
cd backend
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
```

### 2. 패키지 설치
```bash
pip install -r requirements.txt
```
> ⏱ DeepFace는 첫 실행 시 모델 파일을 자동 다운로드합니다 (~500MB)

### 3. 서버 실행
```bash
python main.py
# → http://localhost:8000 에서 실행됨
```

### 4. 프론트엔드 열기
```
frontend/index.html 를 브라우저에서 직접 열거나
로컬 서버로 서빙: python -m http.server 3000 (frontend/ 폴더 안에서)
```

---

## 🧠 감정 → 지표 변환 공식

| 지표 | 사용 감정 |
|------|-----------|
| 자신감 | happy + neutral |
| 긴장도 | fear + sad + angry |
| 안정도 | 100 - 긴장도 |

---

## ⚡ CPU 성능 팁

| 설정 | 내용 |
|------|------|
| `detector_backend` | `"opencv"` (가장 빠름) |
| 분석 간격 | 기본 2.5초 (슬라이더로 조절) |
| JPEG 품질 | 0.7 (프론트에서 압축 전송) |

GPU 없이도 CPU 2.5초 간격이면 실시간처럼 동작합니다.

---

## 🔌 WebSocket API

**클라이언트 → 서버**
```json
{ "frame": "data:image/jpeg;base64,..." }
```

**서버 → 클라이언트**
```json
{
  "confidence": 72.3,
  "tension": 15.1,
  "stability": 84.9,
  "latency_ms": 320.5,
  "raw": {
    "angry": 3.1,
    "disgust": 1.2,
    "fear": 5.0,
    "happy": 45.2,
    "sad": 6.9,
    "surprise": 4.0,
    "neutral": 34.6
  }
}
```
