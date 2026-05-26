import asyncio
import json
import time
import io
import subprocess
import tempfile
import os

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel

app = FastAPI(title="Audio STT Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

print("[STT] Whisper 모델 로딩 중...")
model = WhisperModel("base", device="cpu", compute_type="int8")
print("[STT] Whisper 모델 로드 완료!")


def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> dict:
    """누적된 audio bytes → ffmpeg 변환 → Whisper 전사
    suffix: 입력 파일 확장자 (.webm, .mp4, .wav 등)
    """
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        input_path = f.name

    try:
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", input_path,
            "-ar", "16000",   # Whisper 요구 샘플레이트
            "-ac", "1",       # mono
            "-f", "f32le",    # float32 little-endian raw
            "pipe:1"
        ], capture_output=True, check=True)

        audio_array = np.frombuffer(result.stdout, dtype=np.float32)

        if len(audio_array) == 0:
            return {"text": "", "language": "ko", "duration": 0.0}

        segments, info = model.transcribe(
            audio_array,
            language="ko",
            task="transcribe",
            beam_size=5,
            vad_filter=True,
        )

        text = " ".join(seg.text for seg in segments).strip()
        return {
            "text": text,
            "language": info.language,
            "duration": round(info.duration, 2),
        }

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg 변환 실패: {e.stderr.decode()}") from e
    finally:
        os.unlink(input_path)


# ── HTTP: mp4 파일 업로드 → STT 변환 ─────────────────────────────────────────
@app.post("/transcribe")
async def transcribe_file(file: UploadFile = File(...)):
    """
    mp4 / webm / wav 등 오디오·영상 파일을 받아 Whisper 전사 결과를 반환합니다.
    Content-Type: multipart/form-data, field name: file
    """
    # 지원 확장자 체크 (느슨하게 — ffmpeg이 대부분 처리 가능)
    filename = file.filename or ""
    ext = os.path.splitext(filename)[-1].lower() or ".mp4"
    allowed = {".mp4", ".webm", ".wav", ".mp3", ".m4a", ".ogg", ".flac"}
    if ext not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"지원하지 않는 파일 형식: {ext}. 허용: {', '.join(allowed)}"
        )

    audio_bytes = await file.read()
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")

    t0 = time.perf_counter()
    loop = asyncio.get_event_loop()
    # ext를 suffix로 넘겨 ffmpeg이 컨테이너 형식을 올바르게 감지하게 함
    result = await loop.run_in_executor(None, transcribe, audio_bytes, ext)
    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    result["type"] = "stt_result"

    print(f"[STT/HTTP] 변환 완료 ({result['latency_ms']} ms): {result['text'][:60]}...")
    return result


# ── WebSocket: 실시간 스트리밍 청크 수집 ─────────────────────────────────────
@app.websocket("/ws/stream")
async def stt_ws(websocket: WebSocket):
    await websocket.accept()
    print("[STT] 라우터 연결됨 - 청크 수집 시작")

    audio_buffer = bytearray()

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message:
                audio_buffer.extend(message["bytes"])
                await websocket.send_text(json.dumps({
                    "type": "buffering",
                    "buffered_bytes": len(audio_buffer),
                }))

            elif "text" in message:
                signal = json.loads(message["text"])

                if signal.get("type") == "end_of_audio":
                    print(f"[STT] 종료 신호 수신 - 누적 bytes: {len(audio_buffer)}")

                    if len(audio_buffer) == 0:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": "오디오 데이터 없음"
                        }))
                        continue

                    t0 = time.perf_counter()
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, transcribe, bytes(audio_buffer), ".webm")
                    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                    result["type"] = "stt_result"

                    print(f"[STT] 변환 완료: {result['text'][:50]}...")
                    await websocket.send_text(json.dumps(result, ensure_ascii=False))
                    audio_buffer.clear()

    except WebSocketDisconnect:
        print("[STT] 라우터 연결 끊김")
    except Exception as e:
        print(f"[STT] 오류: {e}")
        await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("test_main:app", host="0.0.0.0", port=8002, reload=True)