import asyncio
import base64
import json
import time
from io import BytesIO

import cv2
import numpy as np
from deepface import DeepFace
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

app = FastAPI(title="Interview Emotion Analyzer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 감정 → 자신감 / 긴장도 변환 ──────────────────────────────────────────────

def calc_metrics(emotions: dict) -> dict:
    """
    DeepFace 7감정 → 자신감 / 긴장도 / 안정도
    emotions 값은 0~100 퍼센트
    """
    confidence = emotions.get("happy", 0) + emotions.get("neutral", 0)
    tension    = emotions.get("fear", 0)  + emotions.get("sad", 0) + emotions.get("angry", 0)
    stability  = max(0, 100 - tension)    # 부가 지표: 안정도

    return {
        "confidence": round(min(confidence, 100), 1),
        "tension":    round(min(tension,    100), 1),
        "stability":  round(stability,            1),
        "raw":        {k: round(v, 1) for k, v in emotions.items()},
    }


def decode_frame(b64_data: str) -> np.ndarray:
    """Base64 이미지 → OpenCV ndarray"""
    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]
    img_bytes = base64.b64decode(b64_data)
    img = Image.open(BytesIO(img_bytes)).convert("RGB")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def analyze_frame(frame: np.ndarray) -> dict:
    """DeepFace 분석 (CPU-friendly 백엔드: opencv)"""
    result = DeepFace.analyze(
        img_path=frame,
        actions=["emotion"],
        detector_backend="opencv",   # 가장 빠름 (CPU)
        enforce_detection=False,     # 얼굴 없어도 에러 안 냄
        silent=True,
    )
    # 결과가 리스트일 수 있음 (멀티페이스 대응)
    emotions = result[0]["emotion"] if isinstance(result, list) else result["emotion"]
    return calc_metrics(emotions)


# ── WebSocket 엔드포인트 ───────────────────────────────────────────────────────

@app.websocket("/ws/emotion")
async def emotion_ws(websocket: WebSocket):
    await websocket.accept()
    print("[WS] 클라이언트 연결됨")

    try:
        while True:
            raw = await websocket.receive_text()
            payload = json.loads(raw)
            frame_b64 = payload.get("frame")

            if not frame_b64:
                continue

            t0 = time.perf_counter()

            # CPU 블로킹 작업을 스레드풀로 분리 → 이벤트루프 안 막힘
            loop = asyncio.get_event_loop()
            frame = decode_frame(frame_b64)
            metrics = await loop.run_in_executor(None, analyze_frame, frame)

            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            metrics["latency_ms"] = elapsed_ms

            await websocket.send_text(json.dumps(metrics))

    except WebSocketDisconnect:
        print("[WS] 클라이언트 연결 끊김")
    except Exception as e:
        print(f"[WS] 오류: {e}")
        await websocket.send_text(json.dumps({"error": str(e)}))


# ── 헬스체크 ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
