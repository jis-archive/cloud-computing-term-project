// ── 설정 ──────────────────────────────────────────────────────────────────
const WS_PROTOCOL = location.protocol === "https:" ? "wss" : "ws";
const HTTP_PROTOCOL = location.protocol === "https:" ? "https" : "http";
const BASE_WS = `${WS_PROTOCOL}://${location.host}`;
const BASE_HTTP = `${HTTP_PROTOCOL}://${location.host}`;

const WS_URL = `${BASE_WS}/ws/video`;
const LLM_URL = `${BASE_HTTP}/feedback`;
const TRANSCRIBE_URL = `${BASE_HTTP}/transcribe`;

const EMOTION_LABELS = { angry: "분노", disgust: "혐오", fear: "두려움", happy: "행복", sad: "슬픔", surprise: "놀람", neutral: "중립" };
const EMOTION_COLORS = { angry: "#ef4444", disgust: "#a855f7", fear: "#f59e0b", happy: "#10b981", sad: "#3b82f6", surprise: "#06b6d4", neutral: "#94a3b8" };

let latestEmotionResult = null;
let latestSttResult = null;

let ws = null;
let stream = null;
let intervalId = null;
let intervalSec = 2.5;
let historyConf = [];
let historyTens = [];
const MAX_HISTORY = 30;

// ── mp4 파일 업로드 → STT ─────────────────────────────────────────────────
async function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    console.log(`[Upload] 파일 선택: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)} MB)`);

    const statusEl = document.getElementById("upload-status");
    if (statusEl) statusEl.textContent = "STT 변환 중...";

    const formData = new FormData();
    formData.append("file", file);

    try {
        const resp = await fetch(TRANSCRIBE_URL, {
            method: "POST",
            body: formData,
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || `HTTP ${resp.status}`);
        }

        const result = await resp.json();
        console.log("[Upload] STT 완료:", result);

        latestSttResult = {
            text: result.text ?? "",
            language: result.language ?? "ko",
            duration: result.duration ?? 0,
        };

        if (statusEl) {
            statusEl.textContent = `변환 완료 (${result.latency_ms} ms) — "${result.text.slice(0, 40)}..."`;
        }

        if (latestEmotionResult) {
            openModal();
        }

    } catch (err) {
        console.error("[Upload] STT 실패:", err);
        if (statusEl) statusEl.textContent = `오류: ${err.message}`;
    }
}

// ── WebSocket ─────────────────────────────────────────────────────────────
function connectWS() {
    ws = new WebSocket(WS_URL);
    ws.onopen = () => { setStatus("connected", "연결됨"); startLoop(); };
    ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        if (data.error) { console.error("서버 오류:", data.error); return; }
        updateUI(data);
    };
    ws.onclose = () => { setStatus("", "연결 끊김"); stopLoop(); };
    ws.onerror = () => setStatus("error", "연결 오류");
}

// ── 카메라 ────────────────────────────────────────────────────────────────
async function startCamera() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
        document.getElementById("video").srcObject = stream;
        document.getElementById("btn-start").disabled = true;
        document.getElementById("btn-stop").disabled = false;
        connectWS();
        connectAudioWS();
    } catch (err) {
        alert("카메라 접근 실패: " + err.message);
    }
}

function stopCamera() {
    stopLoop();

    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.onstop = () => {
            if (audioWs && audioWs.readyState === WebSocket.OPEN) {
                audioWs.send(JSON.stringify({ type: "end_of_audio" }));
                console.log("[Audio] end_of_audio 전송 — STT 대기 중...");
            }
            
            if (audioStream) {
                audioStream.getTracks().forEach(t => t.stop());
                audioStream = null;
            }
        };
        mediaRecorder.stop();
    } else {
        openModal();
    }

    if (ws) { ws.close(); ws = null; }
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
    if (audioStream) {
        audioStream.getTracks().forEach(t => t.stop());
        audioStream = null;
    }
    
    document.getElementById("video").srcObject = null;
    document.getElementById("btn-start").disabled = false;
    document.getElementById("btn-stop").disabled = true;
    setStatus("", "연결 대기중");
}

// ── 오디오 WS (실시간 마이크) ────────────────────────────────────────────
let audioWs = null;
let mediaRecorder = null;
let audioStream = null;

async function connectAudioWS() {
    try {
        audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
        console.warn("[Audio] 마이크 접근 실패 — 파일 업로드 모드로 전환:", err.message);
        return;
    }

    audioWs = new WebSocket(`${BASE_WS}/ws/audio`);

    audioWs.onopen = () => {
        console.log("[Audio WS] 연결됨");

        mediaRecorder = new MediaRecorder(audioStream, { mimeType: "audio/webm" });

        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0 && audioWs.readyState === WebSocket.OPEN) {
                audioWs.send(e.data);
            }
        };

        mediaRecorder.start(2500);
    };

    audioWs.onmessage = (e) => {
        const msg = JSON.parse(e.data);

        if (msg.type === "buffering") {
            console.log(`[Audio] 버퍼링 중: ${msg.buffered_bytes} bytes`);
            return;
        }

        if (msg.type === "stt_result") {
            latestSttResult = {
                text: msg.text ?? "",
                language: msg.language ?? "ko",
                duration: msg.duration ?? 0,
            };
            console.log("[STT] 변환 완료:", latestSttResult.text);
            openModal();
            return;
        }

        if (msg.type === "error") {
            console.error("[STT] 오류:", msg.message);
            openModal();
            if (audioWs) { audioWs.close(); audioWs = null; }
            return;
        }
    };

    audioWs.onclose = () => console.log("[Audio WS] 연결 끊김");
    audioWs.onerror = (e) => console.error("[Audio WS] 오류", e);
}

// ── 모달 열기/닫기 ────────────────────────────────────────────────────────
function openModal() {
    const modal = document.getElementById("feedback-modal");
    document.getElementById("modal-body").innerHTML = '<div class="spinner">피드백 생성 중...</div>';
    modal.classList.add("open");
    requestFeedback();
}

function closeModal() {
    document.getElementById("feedback-modal").classList.remove("open");
}

// ── LLM 피드백 요청 ───────────────────────────────────────────────────────
async function requestFeedback() {
    if (!latestSttResult) {
        const arrived = await waitForStt(30000);
        if (!arrived) {
            console.warn("[Feedback] STT 타임아웃 — 감정 데이터만으로 피드백 진행");
        }
    }

    const emotion = latestEmotionResult ?? { confidence: 0, tension: 0, stability: 0, raw: {} };
    const stt = latestSttResult ?? { text: "", language: "ko", duration: 0 };

    console.log("[Feedback] 요청 payload:", { stt_result: stt, emotion_result: emotion });

    try {
        const res = await fetch(LLM_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ stt_result: stt, emotion_result: emotion }),
        });

        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderFeedback(data);

    } catch (err) {
        document.getElementById("modal-body").innerHTML = `
      <div class="fb-text" style="color:var(--accent-red)">
        ⚠️ 피드백 생성 실패: ${err.message}
      </div>`;
    }
}

function waitForStt(timeoutMs) {
    return new Promise((resolve) => {
        const interval = setInterval(() => {
            if (latestSttResult) { clearInterval(interval); clearTimeout(timeout); resolve(true); }
        }, 200);
        const timeout = setTimeout(() => { clearInterval(interval); resolve(false); }, timeoutMs);
    });
}

// ── 피드백 렌더링 ─────────────────────────────────────────────────────────
function renderFeedback(data) {
    const speech = data.speech_feedback ?? {};
    const emotion = data.emotion_feedback ?? {};
    const score = data.overall_score ?? "--";

    const makeTagList = (arr = [], cls) =>
        arr.map(t => `<span class="tag ${cls}">${t}</span>`).join("");

    document.getElementById("modal-body").innerHTML = `
    <div class="score-ring">
      <div class="score-number">${score}<span style="font-size:24px;color:var(--text-muted)">/10</span></div>
      <div class="score-label">종합 점수</div>
    </div>

    <div class="fb-section">
      <div class="fb-section-title">종합 피드백</div>
      <div class="fb-text">${data.overall_feedback ?? ""}</div>
    </div>

    <div class="fb-section">
      <div class="fb-section-title">발화 분석</div>
      <div class="fb-text" style="color:var(--text-muted);font-size:13px;margin-bottom:8px">
        "${speech.summary ?? ""}"
      </div>
      <div class="tag-list">${makeTagList(speech.strengths, "green")}</div>
    </div>

    <div class="fb-section">
      <div class="fb-section-title">개선할 점</div>
      <div class="tag-list">${makeTagList(speech.improvements, "amber")}</div>
    </div>

    <div class="fb-section">
      <div class="fb-section-title">추천 표현</div>
      <div class="tag-list">${makeTagList(speech.better_expressions, "blue")}</div>
    </div>

    <div class="fb-section">
      <div class="fb-section-title">감정 · 태도 분석</div>
      <div class="fb-text">${emotion.assessment ?? ""}</div>
      <div class="tag-list" style="margin-top:8px">${makeTagList(emotion.tips, "amber")}</div>
    </div>
  `;
}

// ── 캡처 & 전송 루프 ──────────────────────────────────────────────────────
function startLoop() {
    stopLoop();
    intervalId = setInterval(captureAndSend, intervalSec * 1000);
}

function stopLoop() {
    if (intervalId) { clearInterval(intervalId); intervalId = null; }
}

function captureAndSend() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const video = document.getElementById("video");
    const canvas = document.getElementById("canvas");
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0);
    const b64 = canvas.toDataURL("image/jpeg", 0.7);

    document.getElementById("analyzing-indicator").classList.add("active");
    ws.send(JSON.stringify({ frame: b64 }));
    setTimeout(() => document.getElementById("analyzing-indicator").classList.remove("active"), 400);
}

// ── UI 업데이트 ───────────────────────────────────────────────────────────
function updateUI(data) {
    document.getElementById("latency-display").textContent = `${data.latency_ms} ms`;
    setMetric("confidence", data.confidence);
    setMetric("tension", data.tension);
    setMetric("stability", data.stability);
    updateFeedback(data.confidence, data.tension);
    updateEmotionGrid(data.raw);

    historyConf.push(data.confidence);
    historyTens.push(data.tension);
    if (historyConf.length > MAX_HISTORY) { historyConf.shift(); historyTens.shift(); }
    drawHistory();

    latestEmotionResult = {
        confidence: data.confidence,
        tension: data.tension,
        stability: data.stability,
        raw: data.raw,
    };
}

function setMetric(name, value) {
    const el = document.getElementById(`${name}-value`);
    const fill = document.getElementById(`${name}-fill`);
    if (!el) return;
    el.textContent = value + "%";
    fill.style.width = Math.min(value, 100) + "%";
}

function updateFeedback(conf, tens) {
    const el = document.getElementById("face-feedback");
    if (conf >= 60 && tens <= 30) { el.textContent = "😊 좋은 표정입니다! 자신감이 느껴집니다."; el.className = "good"; }
    else if (tens >= 60) { el.textContent = "😰 긴장이 많이 감지됩니다. 심호흡 해보세요."; el.className = "bad"; }
    else if (conf < 40) { el.textContent = "🙂 조금 더 밝은 표정을 지어보세요."; el.className = "warn"; }
    else { el.textContent = "👍 양호한 상태입니다."; el.className = "good"; }
}

function updateEmotionGrid(raw) {
    if (!raw) return;
    const grid = document.getElementById("emotion-grid");
    grid.innerHTML = "";
    const order = ["happy", "neutral", "fear", "sad", "angry", "surprise", "disgust"];
    order.forEach(key => {
        const val = raw[key] ?? 0;
        const cell = document.createElement("div");
        cell.className = "emotion-cell";
        const color = EMOTION_COLORS[key] || "#94a3b8";
        cell.innerHTML = `
      <div class="emotion-name">${EMOTION_LABELS[key] || key}</div>
      <div class="emotion-val" style="color:${val > 30 ? color : 'var(--text-primary)'}">${val}%</div>
    `;
        grid.appendChild(cell);
    });
}

// ── 히스토리 캔버스 ───────────────────────────────────────────────────────
function drawHistory() {
    const canvas = document.getElementById("history-canvas");
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth;
    const H = canvas.offsetHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    const drawLine = (data, color) => {
        if (data.length < 2) return;
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.lineJoin = "round";
        data.forEach((v, i) => {
            const x = (i / (MAX_HISTORY - 1)) * W;
            const y = H - (v / 100) * H;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        });
        ctx.stroke();
        ctx.globalAlpha = .12;
        ctx.fillStyle = color;
        ctx.lineTo((data.length - 1) / (MAX_HISTORY - 1) * W, H);
        ctx.lineTo(0, H);
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;
    };

    drawLine(historyConf, "#10b981");
    drawLine(historyTens, "#ef4444");

    ctx.font = "10px 'Space Mono'";
    ctx.fillStyle = "#10b981"; ctx.fillText("자신감", 8, 14);
    ctx.fillStyle = "#ef4444"; ctx.fillText("긴장도", 8, 28);
}

// ── 유틸 ──────────────────────────────────────────────────────────────────
function setStatus(cls, text) {
    document.getElementById("status-dot").className = cls;
    document.getElementById("status-text").textContent = text;
}

function updateInterval(val) {
    intervalSec = parseFloat(val);
    document.getElementById("interval-label").textContent = val + "s";
    if (intervalId) startLoop();
}
