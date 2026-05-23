import asyncio
import json
import time
import io
import subprocess
import tempfile
import os

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from faster_whisper import WhisperModel

app = FastAPI(title="Audio STT Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

print("[STT] Whisper 모델 로딩 중...")
model = WhisperModel("base", device="cpu", compute_type="int8")
print("[STT] Whisper 모델 로드 완료!")


def transcribe(audio_bytes: bytes) -> dict:
    """누적된 webm bytes → ffmpeg 변환 → Whisper 전사"""
    
    # 1. webm 임시 파일 저장
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio_bytes)
        webm_path = f.name

    try:
        # 2. ffmpeg: webm → 16kHz mono PCM float32 raw
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", webm_path,
            "-ar", "16000",   # Whisper 요구 샘플레이트
            "-ac", "1",       # mono
            "-f", "f32le",    # float32 little-endian raw
            "pipe:1"          # stdout으로 출력
        ], capture_output=True, check=True)

        # 3. raw bytes → numpy float32 배열
        audio_array = np.frombuffer(result.stdout, dtype=np.float32)

        if len(audio_array) == 0:
            return {"text": "", "language": "ko", "duration": 0.0}

        # 4. Whisper 전사
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
        os.unlink(webm_path)  # 임시 파일 정리


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
                print("음성 데이터 수집중...")

            # 면접 종료 신호 수신 → 일괄 변환
            elif "text" in message:
                signal = json.loads(message["text"])

                if signal.get("type") == "end_of_audio":
                    print(f"[STT] 종료 신호 수신 - 누적 bytes: {len(audio_buffer)}")

                    if len(audio_buffer) == 0:
                        await websocket.send_text(json.dumps({"type": "error", "message": "오디오 데이터 없음"}))
                        continue

                    t0 = time.perf_counter()
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(None, transcribe, bytes(audio_buffer))
                    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                    result["type"] = "stt_result"

                    print(f"[STT] 변환 완료: {result['text'][:50]}...")
                    await websocket.send_text(json.dumps(result, ensure_ascii=False))

                    audio_buffer.clear()   # 버퍼 초기화 (다음 면접 대비)

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
    uvicorn.run("main:app", host="0.0.0.0", port=8002, reload=True)