import asyncio
import json
import time
import os
import tempfile
import groq

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Audio STT Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

groq_client = groq.AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

print("[STT] Groq 비동기 클라이언트 초기화 완료!")


async def transcribe(audio_bytes: bytes) -> dict:
    """누적된 webm bytes → ffmpeg으로 mp3 변환 → Groq Whisper 전사"""
 
    # 1. webm 임시 파일 저장
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio_bytes)
        webm_path = f.name
 
    mp3_path = webm_path.replace(".webm", ".mp3")
 
    try:
        # 2. ffmpeg: webm → mp3 (Groq API 지원 포맷)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", webm_path,
            "-ar", "16000", "-ac", "1", "-b:a", "64k", mp3_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
 
        if proc.returncode != 0:
            error_msg = stderr.decode(errors='ignore')
            raise RuntimeError(f"ffmpeg 변환 에러 (Exit Code {proc.returncode}): {error_msg}")

        if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
            raise FileNotFoundError("ffmpeg 변환 결과물(MP3) 파일이 생성되지 않았거나 비어 있습니다.")
 
        # 3. Groq Whisper API 비동기 호출 (await 활용)
        with open(mp3_path, "rb") as audio_file:
            t0 = time.perf_counter()
            response = await groq_client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=audio_file,
                language="ko",
                response_format="verbose_json",
            )
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
 
        return {
            "text": response.text.strip(),
            "language": response.language if hasattr(response, "language") else "ko",
            "duration": round(response.duration, 2) if hasattr(response, "duration") else 0.0,
            "latency_ms": latency_ms,
        }
 
    finally:
        if os.path.exists(webm_path):
            os.unlink(webm_path)
        if os.path.exists(mp3_path):
            os.unlink(mp3_path)


@app.websocket("/ws/stream")
async def stt_ws(websocket: WebSocket):
    await websocket.accept()
    print("[STT] 라우터 연결됨 - 청크 수집 시작")

    audio_buffer = bytearray()   # 청크 누적 버퍼

    try:
        while True:
            message = await websocket.receive()

            # 오디오 청크 수신 → 버퍼에 누적
            if "bytes" in message:
                audio_buffer.extend(message["bytes"])
                await websocket.send_text(json.dumps({
                    "type": "buffering",
                    "buffered_bytes": len(audio_buffer),
                }))

            # 면접 종료 신호 수신 → 일괄 변환
            elif "text" in message:
                signal = json.loads(message["text"])

                if signal.get("type") == "end_of_audio":
                    print(f"[STT] 종료 신호 수신 - 누적 bytes: {len(audio_buffer)}")

                    if len(audio_buffer) == 0:
                        await websocket.send_text(json.dumps({"type": "error", "message": "오디오 데이터 없음"}))
                        continue

                    try:
                        t0 = time.perf_counter()
                        result = await transcribe(bytes(audio_buffer))
                        result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                        result["type"] = "stt_result"

                        print(f"[STT] 변환 완료: {result['text'][:50]}...")
                        await websocket.send_text(json.dumps(result, ensure_ascii=False))
                    except Exception as trans_err:
                        print(f"[STT] 오디오 인코딩 및 Whisper API 오류 발생: {trans_err}")
                        await websocket.send_text(json.dumps({
                            "type": "error", 
                            "message": f"STT 변환 실패: {str(trans_err)}"
                        }))
                    finally:
                        audio_buffer.clear()

    except WebSocketDisconnect:
        print("[STT] 라우터 연결 끊김")
    except Exception as e:
        print(f"[STT] 최상위 루프 위험 오류: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)
