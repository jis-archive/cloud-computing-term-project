import asyncio
import json
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import websockets
import httpx

app = FastAPI(title="Interview Multimodal Router Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

VIDEO_SERVICE_URL = os.getenv("VIDEO_MODEL_URL",  "ws://localhost:8001/ws/analyze")
AUDIO_SERVICE_URL = os.getenv("AUDIO_MODEL_URL",  "ws://localhost:8002/ws/stream")
STT_SERVICE_URL   = os.getenv("STT_SERVICE_URL",  "http://localhost:8002")
LLM_SERVICE_URL   = os.getenv("LLM_SERVICE_URL",  "http://localhost:8003/feedback")


# ── 영상 WebSocket 라우팅 ────────────────────────────────────────────────────
@app.websocket("/ws/video")
async def video_router(client_ws: WebSocket):
    await client_ws.accept()
    print("[Router] 프론트엔드 영상 웹소켓 연결 성공")

    try:
        async with websockets.connect(VIDEO_SERVICE_URL) as backend_ws:
            print(f"[Router] 영상 분석 백엔드({VIDEO_SERVICE_URL}) 연결 성공")
            while True:
                client_data = await client_ws.receive_text()
                await backend_ws.send(client_data)
                analysis_result = await backend_ws.recv()
                await client_ws.send_text(analysis_result)

    except WebSocketDisconnect:
        print("[Router] 프론트엔드 영상 웹소켓 연결 끊김")
    except websockets.exceptions.ConnectionClosed:
        print("[Router] 영상 분석 백엔드 서버와의 연결이 끊겼습니다.")
    except Exception as e:
        print(f"[Router] 영상 라우팅 중 에러 발생: {e}")
        try:
            await client_ws.send_text(json.dumps({"error": f"Video routing error: {str(e)}"}))
        except Exception:
            pass


# ── 음성 WebSocket 라우팅 (실시간 마이크) ────────────────────────────────────
@app.websocket("/ws/audio")
async def audio_router(client_ws: WebSocket):
    await client_ws.accept()
    print("[Router] 프론트엔드 음성 웹소켓 연결 성공")

    try:
        async with websockets.connect(AUDIO_SERVICE_URL) as backend_ws:
            print(f"[Router] 음성 인식 백엔드({AUDIO_SERVICE_URL}) 연결 성공")

            while True:
                message = await client_ws.receive()

                # 클라이언트 disconnect 메시지 감지 → 루프 탈출
                if message.get("type") == "websocket.disconnect":
                    print("[Router] 프론트엔드 음성 웹소켓 연결 끊김 (disconnect 메시지)")
                    break

                if "bytes" in message:
                    await backend_ws.send(message["bytes"])
                    stt_result = await backend_ws.recv()
                    await client_ws.send_text(stt_result)

                elif "text" in message:
                    signal = json.loads(message["text"])

                    if signal.get("type") == "end_of_audio":
                        print("[Router] 면접 종료 신호 수신 → STT 서비스로 전달")
                        await backend_ws.send(json.dumps({"type": "end_of_audio"}))

                        stt_result = await backend_ws.recv()
                        parsed = json.loads(stt_result)
                        text = parsed.get("text", "")
                        print(f"[STT 결과] '{text[:80]}'" if text else "[STT 결과] (빈 텍스트 — 음성 인식 실패)")
                        await client_ws.send_text(stt_result)
                        # end_of_audio 처리 완료 → 루프 종료
                        break

    except WebSocketDisconnect:
        print("[Router] 프론트엔드 음성 웹소켓 연결 끊김")
    except websockets.exceptions.ConnectionClosed:
        print("[Router] 음성 인식 백엔드 서버와의 연결이 끊겼습니다.")
    except Exception as e:
        print(f"[Router] 음성 라우팅 중 에러 발생: {e}")
        try:
            await client_ws.send_text(json.dumps({"error": f"Audio routing error: {str(e)}"}))
        except Exception:
            pass  # 이미 연결이 끊긴 경우 무시


# ── mp4/wav 파일 업로드 → STT 서비스 프록시 ─────────────────────────────────
@app.post("/transcribe")
async def transcribe_proxy(file: UploadFile = File(...)):
    """
    mp4 / wav / webm 등 파일을 받아 STT 서비스로 전달하고 결과를 반환합니다.
    프론트엔드: multipart/form-data, field name = file
    """
    audio_bytes = await file.read()
    filename    = file.filename or "upload.mp4"

    print(f"[Router] 파일 수신: {filename} ({len(audio_bytes):,} bytes) → STT 서비스로 전달")

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{STT_SERVICE_URL}/transcribe",
            files={"file": (filename, audio_bytes, file.content_type or "video/mp4")},
        )

    if resp.status_code != 200:
        return JSONResponse(
            status_code=resp.status_code,
            content={"error": f"STT 서비스 오류: {resp.text}"},
        )

    result = resp.json()
    text = result.get("text", "")
    print(f"[Router] STT 완료: '{text[:60]}'" if text else "[Router] STT 완료: (빈 텍스트 — 음성 인식 실패)")
    return result


# ── LLM 피드백 프록시 ────────────────────────────────────────────────────────
@app.post("/feedback")
async def feedback_proxy(request: Request):
    body = await request.json()
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(LLM_SERVICE_URL, json=body)
    return resp.json()


# ── 헬스체크 ─────────────────────────────────────────────────────────────────
@app.get("/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("test_main:app", host="0.0.0.0", port=8000, reload=True)