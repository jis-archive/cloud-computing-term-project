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
let intervalSec = 1.0;
let historyConf = [];
let historyTens = [];
const MAX_HISTORY = 30;

let interviewSessionHistory = [];
let currentTurnAnswer = "";

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
        const jobInput = document.getElementById("job-input");
        const selectedJob = jobInput ? jobInput.value.trim() : "개발자";
        if (jobInput) jobInput.disabled = true;
        
        entireInterviewTranscript = "";
        latestSttResult = null;
        latestEmotionResult = null;
        historyConf = [];
        historyTens = [];
        interviewSessionHistory = [];
        currentTurnAnswer = "";

        const chatLog = document.getElementById("chat-log");
        if (chatLog) {
            chatLog.innerHTML = `<div class="chat-message system">LLM 면접관이 ${selectedJob} 면접의 첫 질문을 출제하고 있습니다...</div>`;
        }
        
        try {
            const response = await fetch(LLM_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    is_start: true,
                    job: selectedJob,
                    text: ""
                })
            });
            if (!response.ok) throw new Error(`HTTP Error ${response.status}`);
            
            const data = await response.json();
            
            if (chatLog) {
                chatLog.innerHTML = `<div class="chat-message system">모의 면접 세션이 개시되었습니다.</div>`;
                appendChatLog("interviewer", data.message);
                interviewSessionHistory.push({ role: "interviewer", text: data.message });
            }
        } catch (llmErr) {
            console.error("[LLM Start] 면접 오프닝 로드 실패:", llmErr);
            appendChatLog("interviewer", `안녕하세요. 연결 상태가 원활하지 않아 기본 공통 질문을 드립니다. ${selectedJob} 직무에 지원하게 된 동기와 준비 과정에 대해 말씀해 주세요.`);
        }
        
        ["confidence", "tension", "stability"].forEach(name => {
            const valEl = document.getElementById(`${name}-value`);
            const fillEl = document.getElementById(`${name}-fill`);
            if (valEl) valEl.textContent = "--";
            if (fillEl) fillEl.style.width = "0%";
        });
        
        const feedbackEl = document.getElementById("face-feedback");
        if (feedbackEl) {
            feedbackEl.innerText = "얼굴 감지 시스템 가동 중...";
            feedbackEl.className = ""; 
        }
        
        const emotionGrid = document.getElementById("emotion-grid");
        if (emotionGrid) {
            emotionGrid.innerHTML = '<div class="empty-state" style="grid-column:1/3">분석 대기 중...</div>';
        }
        
        const canvas = document.getElementById("history-canvas");
        if (canvas) {
            const ctx = canvas.getContext("2d");
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        }
        
        const statusEl = document.getElementById("upload-status");
        if (statusEl) {
            statusEl.textContent = "";
            statusEl.style.display = "none";
        }

        stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
        document.getElementById("video").srcObject = stream;
        document.getElementById("btn-start").style.display = "none";
        document.getElementById("btn-stop").style.display = "block";
        
        connectWS();
        connectAudioWS();
    } catch (err) {
        alert("카메라 접근 실패: " + err.message);
    }
}

function stopCamera() {
    stopLoop();
    stopMicVolumeAnalysis();
    resetSilenceTimer();
    isAudioRecording = false;

    const jobInput = document.getElementById("job-input");
    if (jobInput) jobInput.disabled = false;

    if (stream) {
        stream.getTracks().forEach(track => {
            track.stop();
            console.log(`[Camera] 비디오 트랙 해제 완료: ${track.label}`);
        });
        stream = null;
    }

    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.onstop = async () => {
            if (sentenceChunks.length > 0 && audioWs && audioWs.readyState === WebSocket.OPEN) {
                await sendCurrentSentence();
            }
            
            if (audioStream) {
                audioStream.getTracks().forEach(t => t.stop());
                audioStream = null;
            }
            
            if (ws) { ws.close(); ws = null; }
            if (audioWs) { audioWs.close(); audioWs = null; }
            
            openModal();
        };
        mediaRecorder.stop();
    } else {
        if (audioStream) {
            audioStream.getTracks().forEach(t => t.stop());
            audioStream = null;
        }
        if (ws) { ws.close(); ws = null; }
        if (audioWs) { audioWs.close(); audioWs = null; }
        openModal();
    }

    document.getElementById("video").srcObject = null;
    document.getElementById("btn-start").style.display = "block";
    document.getElementById("btn-stop").style.display = "none";
    setStatus("", "연결 대기중");
}

// ── 오디오 WS (실시간 마이크) ────────────────────────────────────────────
let audioWs = null;
let mediaRecorder = null;
let audioStream = null;
let isAudioRecording = false;

let sentenceChunks = [];
let isSpeaking = false;
let silenceStart = null;
let entireInterviewTranscript = "";

const SILENCE_THRESHOLD = 50;
const SILENCE_DURATION = 800;

async function connectAudioWS() {
    try {
        audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        startMicVolumeAnalysis(audioStream);
        
        audioWs = new WebSocket(`${BASE_WS}/ws/audio`);
        
        audioWs.onopen = () => {
            console.log("[Audio] 게이트웨이 음성 웹소켓 연결 성공");
            sentenceChunks = [];
            isSpeaking = false;
            silenceStart = null;
            isAudioRecording = true;

            startNewSentenceRecorder();
        };
        
        audioWs.onmessage = (event) => {
            const rawMessage = event.data;
            try {
                const dataObj = JSON.parse(rawMessage);

                if (dataObj.type === "stt_result" && dataObj.text) {
                    const extractedText = dataObj.text.trim();
                    const noiseHallucinationFilters = ["안녕하세요.", "감사합니다."];

                    if (noiseHallucinationFilters.includes(extractedText)) {
                        console.warn(`[VAD Filter] 주변 소음으로 인한 환각 단어가 차단되었습니다: "${extractedText}"`);
                        
                        const textPreview = document.getElementById("mic-text-preview");
                        if (textPreview) textPreview.textContent = "음성 입력 대기 중...";
                        return;
                    }

                    if (extractedText.length > 0) {
                        appendChatLog("interviewee", extractedText);
                        entireInterviewTranscript += extractedText + " ";
                        currentTurnAnswer += extractedText + " ";
                        startSilenceTimer();
                        entireInterviewTranscript += extractedText + " ";
                        latestSttResult = dataObj;
                    }
                }
                
                const textPreview = document.getElementById("mic-text-preview");
                if (textPreview) {
                    if (dataObj.type === "buffering") {
                        textPreview.textContent = "음성 신호 압축 처리 중...";
                    } else if (dataObj.type === "stt_result") {
                        textPreview.textContent = "음성 입력 대기 중...";
                    }
                }
            } catch (jsonErr) {
                if (rawMessage && typeof rawMessage === "string" && !rawMessage.startsWith("{")) {
                    appendChatLog("interviewee", rawMessage.trim());
                    entireInterviewTranscript += rawMessage.trim() + " ";
                }
            }
        };
        
        audioWs.onerror = (err) => console.error("[Audio] 소켓 에러:", err);
        audioWs.onclose = () => console.log("[Audio] 소켓 연결 종료");
        
    } catch (err) {
        console.error("[Audio] 마이크 초기화 실패:", err);
    }
}

function startNewSentenceRecorder() {
    if (!audioStream || !isAudioRecording) return;

    mediaRecorder = new MediaRecorder(audioStream, { mimeType: "audio/webm" });
    
    mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
            sentenceChunks.push(e.data);
            
            if (!isSpeaking) {
                if (sentenceChunks.length > 11) { 
                    sentenceChunks.splice(1, 1); 
                }
            }
        }
    };
    
    mediaRecorder.onstop = async () => {
        if (sentenceChunks.length > 0 && audioWs && audioWs.readyState === WebSocket.OPEN) {
            await sendCurrentSentence();
        }
        if (isAudioRecording) {
            startNewSentenceRecorder();
        }
    };
    
    mediaRecorder.start(100);
}

let micAudioContext = null;
let micAnalyser = null;
let micSource = null;
let micAnimationId = null;

function startMicVolumeAnalysis(stream) {
    stopMicVolumeAnalysis();

    try {
        micAudioContext = new (window.AudioContext || window.webkitAudioContext)();
        micAnalyser = micAudioContext.createAnalyser();
        micAnalyser.fftSize = 64;
        
        micSource = micAudioContext.createMediaStreamSource(stream);
        micSource.connect(micAnalyser);
        
        const bufferLength = micAnalyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        
        const outerCircle = document.getElementById("mic-outer");
        const innerCircle = document.getElementById("mic-inner");
        const textPreview = document.getElementById("mic-text-preview");
        
        if (textPreview) textPreview.textContent = "음성 입력 감지 중...";

        function analyzeFrame() {
            if (!micAnalyser) return;
            micAnimationId = requestAnimationFrame(analyzeFrame);
            
            micAnalyser.getByteFrequencyData(dataArray);
            
            let sum = 0;
            for (let i = 0; i < bufferLength; i++) {
                sum += dataArray[i];
            }

            const average = sum / bufferLength;
            const volumeFactor = Math.min(average / 90, 1.0);

            if (outerCircle && innerCircle) {
                const scale = 1.0 + (volumeFactor * 1.3);
                innerCircle.style.transform = `scale(${scale})`;
                outerCircle.style.backgroundColor = `rgba(16, 185, 129, ${0.08 + (volumeFactor * 0.45)})`;
                outerCircle.style.borderColor = `rgba(16, 185, 129, ${0.2 + (volumeFactor * 0.62)})`;
                innerCircle.style.backgroundColor = `rgba(16, 185, 129, ${0.25 + (volumeFactor * 0.65)})`;
                if (volumeFactor > 0.15) outerCircle.style.boxShadow = `0 0 ${volumeFactor * 25}px rgba(16, 185, 129, 0.6)`;
                else outerCircle.style.boxShadow = "none";
            }
            
            handleVoiceActivityDetection(average);
        }
        analyzeFrame();
    } catch (err) {
        console.error("[MicMonitor] Web Audio API 가동 에러:", err);
    }
}

function handleVoiceActivityDetection(averageVolume) {
    if (!audioWs || audioWs.readyState !== WebSocket.OPEN) return;

    if (averageVolume > SILENCE_THRESHOLD) {
        silenceStart = null;
        
        if (!isSpeaking) {
            isSpeaking = true;
            feedSilenceTimer();
            const textPreview = document.getElementById("mic-text-preview");
            if (textPreview) textPreview.textContent = "말하는 중...";
        }
    } else {
        if (isSpeaking) {
            if (silenceStart === null) {
                silenceStart = Date.now();
            } else if (Date.now() - silenceStart >= SILENCE_DURATION) {
                console.log(`[VAD] 문장 마침 확정 (${SILENCE_DURATION}ms 무음 유지). 전송 프로세스 작동.`);
                
                isSpeaking = false;
                silenceStart = null;
                
                const textPreview = document.getElementById("mic-text-preview");
                if (textPreview) textPreview.textContent = "AI 문장 분석 중...";

                if (mediaRecorder && mediaRecorder.state === "recording") {
                    mediaRecorder.stop();
                }
            }
        }
    }
}

async function sendCurrentSentence() {
    if (sentenceChunks.length === 0) return;
    
    const sentenceBlob = new Blob(sentenceChunks, { type: "audio/webm" });
    sentenceChunks = []; 
    
    try {
        const arrayBuffer = await sentenceBlob.arrayBuffer();
        if (audioWs && audioWs.readyState === WebSocket.OPEN) {
            audioWs.send(arrayBuffer);
            audioWs.send(JSON.stringify({ type: "end_of_audio" }));
            console.log("[VAD] 1초 Pre-roll이 포함된 발화 세그먼트 전송 완료");
        }
    } catch (err) {
        console.error("[VAD] 오디오 바이너리 포워딩 실패:", err);
    }
}

function stripMarkdown(text) {
    if (!text) return "";
    return text
        .replace(/\*\*(.*?)\*\*/g, '$1')   // **볼드** -> 볼드
        // .replace(/__(.*?)__/g, '$1')       // __볼드__ -> 볼드
        // .replace(/\*(.*?)\*/g, '$1')       // *이탤릭* -> 이탤릭
        // .replace(/_(.*?)_/g, '$1')         // _이탤릭* -> 이탤릭
        // .replace(/`(.*?)`/g, '$1')         // `코드` -> 코드
        // .replace(/[-*+]\s+/g, '')          // 불필요한 리스트 불릿 기호 제거 (- , * , + )
        // .replace(/#{1,6}\s+/g, '')         // 샵(#) 헤더 표시 제거
        // .replace(/\*\*/g, '')              // 혹시 낱개로 깨져서 남은 볼드 기호 청소
        // .replace(/\*/g, '');               // 혹시 낱개로 깨져서 남은 이탤릭 기호 청소
}

function appendChatLog(sender, text) {
    const chatLog = document.getElementById("chat-log");
    if (!chatLog) return;

    if (sender === "interviewer") {
        text = stripMarkdown(text);
    }
    
    const messageDiv = document.createElement("div");
    messageDiv.className = `chat-message ${sender}`; // interviewee 또는 interviewer 적용
    messageDiv.textContent = text;
    
    chatLog.appendChild(messageDiv);
    
    chatLog.scrollTop = chatLog.scrollHeight;
}

// ── 마이크 분석 엔진 정지 및 리셋 ──────────────────────────────────────
function stopMicVolumeAnalysis() {
    if (micAnimationId) {
        cancelAnimationFrame(micAnimationId);
        micAnimationId = null;
    }
    if (micSource) { micSource.disconnect(); micSource = null; }
    if (micAnalyser) { micAnalyser = null; }
    if (micAudioContext) {
        if (micAudioContext.state !== "closed") micAudioContext.close();
        micAudioContext = null;
    }
    
    // UI 컴포넌트 초기 원상 복구
    const outerCircle = document.getElementById("mic-outer");
    const innerCircle = document.getElementById("mic-inner");
    const textPreview = document.getElementById("mic-text-preview");
    
    if (outerCircle && innerCircle) {
        innerCircle.style.transform = "scale(1)";
        outerCircle.style.backgroundColor = "rgba(16, 185, 129, 0.08)";
        outerCircle.style.borderColor = "rgba(16, 185, 129, 0.2)";
        innerCircle.style.backgroundColor = "rgba(16, 185, 129, 0.25)";
        outerCircle.style.boxShadow = "none";
    }
    if (textPreview) textPreview.textContent = "마이크 입력 꺼짐";
}

let silenceTimeoutId = null;
let timerAnimationFrameId = null;
let silenceStartTime = null;
const SILENCE_LIMIT_MS = 10000;

function startSilenceTimer() {
    resetSilenceTimer();

    silenceStartTime = Date.now();
    const timerBar = document.getElementById("silence-timer-bar");

    silenceTimeoutId = setTimeout(() => {
        triggerSilenceTimeout();
    }, SILENCE_LIMIT_MS);

    function updateProgress() {
        if (!silenceStartTime) return;
        
        const elapsed = Date.now() - silenceStartTime;
        const remainingPercentage = Math.max(0, 100 - (elapsed / SILENCE_LIMIT_MS) * 100);
        
        if (timerBar) {
            timerBar.style.width = `${remainingPercentage}%`;
        }

        if (elapsed < SILENCE_LIMIT_MS) {
            timerAnimationFrameId = requestAnimationFrame(updateProgress);
        }
    }
    timerAnimationFrameId = requestAnimationFrame(updateProgress);
}

function resetSilenceTimer() {
    if (silenceTimeoutId) {
        clearTimeout(silenceTimeoutId);
        silenceTimeoutId = null;
    }
    if (timerAnimationFrameId) {
        cancelAnimationFrame(timerAnimationFrameId);
        timerAnimationFrameId = null;
    }
    silenceStartTime = null;

    const timerBar = document.getElementById("silence-timer-bar");
    if (timerBar) {
        timerBar.style.width = "100%";
    }
}

function feedSilenceTimer() {
    if (!silenceStartTime) return;

    silenceStartTime = Date.now();

    if (silenceTimeoutId) {
        clearTimeout(silenceTimeoutId);
    }
    
    silenceTimeoutId = setTimeout(() => {
        triggerSilenceTimeout();
    }, SILENCE_LIMIT_MS);
}

function triggerSilenceTimeout() {
    resetSilenceTimer();
    interviewSessionHistory.push({ role: "interviewee", text: currentTurnAnswer.trim() });    
    const chatLog = document.getElementById("chat-log");
    if (chatLog) {
        chatLog.scrollTop = chatLog.scrollHeight;
    }
    requestNextTurn();
}

async function requestNextTurn() {
    try {
        const response = await fetch(LLM_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                is_start: false,
                is_chat_turn: true,
                job: window.currentJobTitle || "소프트웨어 개발자",
                history: interviewSessionHistory,
                stt_result: { text: currentTurnAnswer.trim() },
                emotion_result: latestEmotionResult || { confidence: 70, tension: 20, stability: 80 }
            })
        });
        
        const loadingEl = document.getElementById("ai-loading");
        if (loadingEl) loadingEl.remove();

        if (!response.ok) throw new Error(`서버 응답 오류 (HTTP ${response.status})`);
        const data = await response.json();

        let aiMessage = data.message;
        
        const isInterviewFinished = aiMessage.includes("[면접 종료]");
        
        if (isInterviewFinished) {
            aiMessage = aiMessage.replace("[면접 종료]", "").trim();
        }

        appendChatLog("interviewer", aiMessage);
        interviewSessionHistory.push({ role: "interviewer", text: aiMessage });
        currentTurnAnswer = "";
        
        if (isInterviewFinished) {
            appendChatLog("system", "AI 면접관이 질문을 모두 마쳤습니다.");
            stopCamera();
            return; 
        }
        
    } catch (err) {
        console.error("[Turn Interaction Error] 면접관 소통 장애:", err);
        const loadingEl = document.getElementById("ai-loading");
        if (loadingEl) loadingEl.remove();
        appendChatLog("interviewer", "죄송합니다 지원자님, 답변 컨텍스트 수신 중 일시적인 지연이 발생했습니다. 말씀을 이어서 해주세요.");
    }
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
    const totalRecords = historyConf.length;
    const avgConfidence = totalRecords > 0 ? (historyConf.reduce((a, b) => a + b, 0) / totalRecords) : 0;
    const avgTension = totalRecords > 0 ? (historyTens.reduce((a, b) => a + b, 0) / totalRecords) : 0;
    const avgStability = Math.max(0, 100 - avgTension);
    
    const jobInput = document.getElementById("job-input");
    const selectedJob = jobInput ? jobInput.value.trim() : "개발자";

    const summaryEl = document.getElementById("modal-speech-summary");
    if (summaryEl) summaryEl.textContent = "인공지능이 면접 스크립트 문맥과 표정 흐름을 종합 심사 중입니다...";

    try {
        const response = await fetch(LLM_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                is_start: false,
                is_chat_turn: false,
                job: selectedJob,
                history: interviewSessionHistory,
                emotion_timeline: {
                    avg_confidence: Math.round(avgConfidence * 10) / 10,
                    avg_tension: Math.round(avgTension * 10) / 10,
                    avg_stability: Math.round(avgStability * 10) / 10,
                    confidence_flow: historyConf,
                    tension_flow: historyTens
                }
            })
        });

        if (!response.ok) throw new Error(`HTTP Error ${response.status}`);
        const reportData = await response.json();

        renderFeedback(reportData);

    } catch (err) {
        console.error("[Final Report Error] 종합 피드백 생성 실패:", err);
        if (summaryEl) summaryEl.textContent = "최종 분석 보고서를 생성하는 과정에서 통신 에러가 발생했습니다.";
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

    const corners = document.querySelectorAll(".camera-overlay .corner");
    corners.forEach(corner => corner.classList.add("active"));

    ws.send(JSON.stringify({ frame: b64 }));
    
    setTimeout(() => {
        corners.forEach(corner => corner.classList.remove("active"));
    }, 400);
}

// ── UI 업데이트 ───────────────────────────────────────────────────────────
function updateUI(data) {
    document.getElementById("latency-display").textContent = `${data.latency_ms} ms`;

    if (data.face_detected === false) {
        const feedbackEl = document.getElementById("face-feedback");
        if (feedbackEl) {
            feedbackEl.innerText = "화면에 얼굴이 감지되지 않습니다.\n카메라 정면을 바르게 바라봐주세요.";
            feedbackEl.className = "null";
        }
        return;
    }

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
    if (conf >= 60 && tens <= 30) { el.innerText = "좋은 표정입니다!\n자신감이 느껴집니다."; el.className = "good"; }
    else if (tens >= 60) { el.innerText = "긴장이 많이 감지됩니다.\n심호흡 해보세요."; el.className = "bad"; }
    else if (conf < 40) { el.innerText = "조금 더 밝은 표정을 지어보세요."; el.className = "warn"; }
    else { el.innerText = "양호한 상태입니다."; el.className = "good"; }
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
    document.getElementById("interval-label").textContent = intervalSec.toFixed(1) + "s";
    if (intervalId) startLoop();
}
