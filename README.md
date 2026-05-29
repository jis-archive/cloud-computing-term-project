# 면접 분석 서비스 실행 가이드

## 사전 준비

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) 설치 및 실행
- 프로젝트 루트에 `.env` 파일 생성

```
# .env
GROQ_API_KEY=your_actual_groq_api_key
```

---

## 디렉토리 구조

```
cloud-computing-term-project/
├── docker-compose.yml
├── .env
└── services/
    ├── router/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── frontend/
    │   │   └── index.html
    │   └── src/
    │       └── main.py
    ├── video-analysis/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── src/
    │       └── main.py
    ├── audio-stt/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── src/
    │       └── main.py
    └── llm-feedback/
        ├── Dockerfile
        ├── requirements.txt
        └── src/
            └── main.py
```

---

## 실행 방법

### 1. 빌드 (최초 1회 또는 코드 변경 시)

```bash
docker compose build
```

> video-analysis(DeepFace), audio-stt(Whisper) 는 이미지 크기가 크므로 빌드에 시간이 걸립니다.

### 2. 실행

```bash
docker compose up -d
```

### 3. 상태 확인

```bash
docker compose ps
```

4개 서비스가 모두 `Up` 상태이면 정상입니다.

```
router           Up    0.0.0.0:8000->8000/tcp
video-analysis   Up    0.0.0.0:8001->8001/tcp
audio-stt        Up    0.0.0.0:8002->8002/tcp
llm-feedback     Up    0.0.0.0:8003->8003/tcp
```

### 4. 접속

브라우저에서 아래 주소로 접속합니다.

```
http://localhost:8000
```

---

## 종료 방법

```bash
docker compose down
```

---

## 문제 해결

**로그 확인**
```bash
# 전체 로그
docker compose logs

# 특정 서비스 로그
docker compose logs router
docker compose logs video-analysis
docker compose logs audio-stt
docker compose logs llm-feedback
```

**특정 서비스만 재빌드**
```bash
docker compose build router
docker compose up -d
```

**헬스체크**
```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
```

> `unhealthy` 표시가 있어도 각 헬스체크에서 응답이 오면 정상 동작 중입니다.  
> video-analysis는 TensorFlow 로딩으로 인해 시작이 느릴 수 있습니다.
