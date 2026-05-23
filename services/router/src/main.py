import asyncio
import json
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
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

VIDEO_SERVICE_URL = os.getenv("VIDEO_MODEL_URL", "ws://localhost:8001/ws/analyze")
AUDIO_SERVICE_URL = os.getenv("AUDIO_MODEL_URL", "ws://localhost:8002/ws/stream")
LLM_SERVICE_URL = os.getenv("LLM_SERVICE_URL", "http://localhost:8003/feedback")


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
        await client_ws.send_text(json.dumps({"error": f"Video routing error: {str(e)}"}))
    

@app.websocket("/ws/audio")
async def audio_router(client_ws: WebSocket):
    await client_ws.accept()
    print("[Router] 프론트엔드 음성 웹소켓 연결 성공")

    try:
        async with websockets.connect(AUDIO_SERVICE_URL) as backend_ws:
            print(f"[Router] 음성 인식 백엔드({AUDIO_SERVICE_URL}) 연결 성공")
            
            while True:
                message = await client_ws.receive()  # bytes/text 둘 다 수신

                if "bytes" in message:
                    # 오디오 청크 → STT 서비스로 전달
                    await backend_ws.send(message["bytes"])

                    # STT 서비스의 buffering 응답 수신 후 클라이언트로 전달
                    stt_result = await backend_ws.recv()
                    await client_ws.send_text(stt_result)

                elif "text" in message:
                    signal = json.loads(message["text"])

                    if signal.get("type") == "end_of_audio":
                        print("[Router] 면접 종료 신호 수신 → STT 서비스로 전달")
                        await backend_ws.send(json.dumps({"type": "end_of_audio"}))

                        # Whisper 변환 완료 대기
                        stt_result = await backend_ws.recv()
                        parsed = json.loads(stt_result)

                        print(f"[STT 결과] {parsed.get('text', '')}")
                        await client_ws.send_text(stt_result)
        
        await client_ws.send_text(stt_result)

    except WebSocketDisconnect:
        print("[Router] 프론트엔드 음성 웹소켓 연결 끊김")
    except websockets.exceptions.ConnectionClosed:
        print("[Router] 음성 인식 백엔드 서버와의 연결이 끊겼습니다.")
    except Exception as e:
        print(f"[Router] 음성 라우팅 중 에러 발생: {e}")
        await client_ws.send_text(json.dumps({"error": f"Audio routing error: {str(e)}"}))


@app.post("/feedback")
async def feedback_proxy(request: Request):
    body = await request.json()
    async with httpx.AsyncClient() as client:
        resp = await client.post(LLM_SERVICE_URL, json=body, timeout=30.0)
    return resp.json()


@app.get("/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
