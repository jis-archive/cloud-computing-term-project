import json
import os
import time

import groq
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="LLM Feedback Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

groq_client = groq.Groq(api_key=os.getenv("GROQ_API_KEY"))
print("[LLM] Groq 클라이언트 초기화 완료!")


# ── 데이터 수신 스키마 사양 ───────────────────────────────────────
class FeedbackRequest(BaseModel):
    stt_result: dict = {}
    emotion_result: dict = {}
    is_start: bool = False
    is_chat_turn: bool = False
    job: str = "개발자"
    history: list = []
    emotion_timeline: dict = {}


FEEDBACK_SYSTEM_PROMPT = """
당신은 대한민국 최고 임원진 면접 평가 시스템의 핵심 추론 엔진이자 인사총괄 수석 위원입니다.
지정된 직종(job)에 맞게 지원자가 수행한 전체 대화 내용과 실시간 감정 타임라인 데이터를 '다차원 역량 평가 기준'에 의거하여 엄격하고 논리적으로 심사하십시오.

★ [초정밀] STT 오차 유연성 보정 및 의도적 자질 결함(태도/인성) 감별 매트릭스:
1. (기계적 오타 판정): 발음 유사성으로 뭉개진 표현, 조사 유실, 직무 전공 용어의 맞춤법 변환 오류 등은 '전체 문맥의 기술적 맥락'을 추론하여 지원자가 정상 구사한 것으로 참작하고 기술 점수를 정상 평가하십시오.
2. (자질 결함 및 인성 페널티 판정): 기계적 오타의 범주를 명백히 벗어난 비속어, 욕설, 낙서성 발언, 혹은 면접관을 향한 도발/조롱/비하("AI 주제에", "너나 잘해", "장난치나" 등) 및 고의적인 무성의함은 '조직 적합성 및 직업 윤리(인성)' 지표의 치명적인 결격 사유로 정의합니다.
3. (입체적 감점 산출 메커니즘): 단순 하드코딩 제어가 아닌, 대화 이력에서 발견된 인성 결함의 빈도, 모욕의 강도, 태도의 불성실도를 종합 고려하여 '종합 평가 점수(overall_score)'를 감점 처리하십시오. 욕설이나 비하가 심각할 경우 종합 점수는 과감하게 낙제점(1~3점) 체계로 하락해야 합니다.
4. (리포트 반영): 'speech_feedback.improvements' 및 'overall_feedback' 섹션에 기술적 역량과 별개로 비즈니스 환경에서의 감정 제어 능력, 커뮤니케이션 매너, 프로페셔널리즘 결여에 대한 이성적이고 매서운 인사 훈계 가이드를 명시하십시오.

반드시 아래 지정된 JSON 형식으로만 응답하며, 마크다운 기호 없이 순수 JSON Object 규격만 반환하세요:
{
  "overall_score": <입체 감점 공식이 반영된 종합 점수 1-10 사이 정수>,
  "speech_feedback": {
    "summary": "<전체 발화 내용의 요약과 비즈니스 태도/자질을 입체적으로 요약한 1-2문장>",
    "strengths": ["<답변 구조의 논리적 장점 및 우수했던 직무 역량 1>", "<내용상 유수했던 포인트 2>"],
    "improvements": ["<질문 의도 이탈, 논리적 모순, 혹은 커뮤니케이션 인성 결함에 대한 엄격한 지적 1>", "<기타 내용 보완점 2>"],
    "better_expressions": ["<더 전문적이고 올바른 비즈니스 매너가 반영된 대안 답변 예시 문장 1>", "<대안 예시 문장 2>"]
  },
  "emotion_feedback": {
    "assessment": "<감정 평균 수치와 타임라인 변화를 바탕으로 파악한 심리/비언어적 태도 분석 1-2문장>",
    "tips": ["<긴장 완화 및 진중하고 프로페셔널한 비언어 태도 유지를 위한 팁 1>", "<태도 보정 코칭 팁 2>"]
  },
  "overall_feedback": "<조직 적합성, 인성, 직무 전문성을 종합하여 지원자의 자질을 엄격하게 평가한 종합 코칭 피드백 2-3문장>"
}
"""


def generate_comprehensive_report(job: str, history: list, emotion_data: dict) -> dict:
    """
    분리 전달된 텍스트 이력과 감정 시계열 평균 통계를 결합하여 입체적 피드백 생성
    """
    dialogue_dump = ""
    for turn in history:
        speaker = "AI 면접관" if turn.get("role") == "interviewer" else "지원자"
        dialogue_dump += f"[{speaker}]: {turn.get('text', '')}\n"

    user_message = f"""
선택 직무: [{job}]

[1. 전체 면접 역할별 분류 대화 이력 스크립트]
{dialogue_dump if dialogue_dump else "(진행된 대화 이력 없음)"}

[2. 전체 시간대 실시간 감정 분석 종합 통계 수치]
- 자신감(Confidence) 평균 점수: {emotion_data.get("avg_confidence", 0)}점 / 100점
- 긴장도(Tension) 평균 점수: {emotion_data.get("avg_tension", 0)}점 / 100점
- 안정도(Stability) 평균 점수: {emotion_data.get("avg_stability", 0)}점 / 100점
* 참고: 자신감과 안정도가 높을수록 우수하며, 긴장도가 높을수록 페이스 조절이 필요했음을 뜻합니다.

위 마이크로 데이터들을 심층 분석하여 정해진 JSON 포맷으로 최종 코칭 성적표 리포트를 생성해주세요. 사족은 절대 금지합니다.
"""

    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": FEEDBACK_SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        temperature=0.3,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )

    return json.loads(response.choices[0].message.content)


# ── 엔드포인트 라우팅 매핑 허브 ───────────────────────────────────────
@app.post("/feedback")
async def create_feedback(req: FeedbackRequest):
    t0 = time.perf_counter()

    if req.is_start:
        print(f"[LLM] AI 면접관 최초 오프닝 질문 생성 가동 (직종: {req.job})")
        system_prompt = (
            "당신은 현재 대기업 인사팀 출신의 베테랑 AI 면접관입니다. "
            "지원자가 선택한 직종 컨텍스트에 완벽하게 몰입하여, 지적이고 신뢰감 주는 첫 인사말을 건네세요. "
            "그 직후 해당 직무의 전문성을 검증할 수 있는 첫 번째 핵심 질문을 딱 '하나'만 명확하게 제시하세요.\n"
            "★ 중요 규칙: 가독성을 높이기 위한 마크다운 기호(예: **텍스트**, *텍스트*, # 등)는 절대 사용하지 마십시오. "
            "오직 텍스트 문장과 마침표, 줄바꿈만 사용하여 실제 사람이 말하듯 자연스러운 구어체 대사만 출력하세요."
        )
        user_message = f"지원자가 응시하려는 면접 직종은 [{req.job}] 입니다. 첫인사와 직무 검증 첫 핵심 질문을 생성해 주세요."
        
        response = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.7,
            max_tokens=512,
        )
        opening_question = response.choices[0].message.content.strip()
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"status": "success", "message": opening_question, "latency_ms": elapsed_ms}

    if req.is_chat_turn:
        print(f"[LLM] 실시간 턴제 소통 가동 (수신된 세션 총 턴 수: {len(req.history)})")
        
        system_prompt = (
            f"당신은 현재 [{req.job}] 직무 역량과 비즈니스 인성을 동시에 심사 중인 예리하고 단호한 AI 면접관입니다. "
            "지원자가 직전에 제출한 마지막 답변을 주의 깊게 읽고, 면접관으로서 지적이고 공감 어리거나 혹은 보완점을 짚어주는 "
            "가벼운 반응(Reaction)을 1~2문장으로 먼저 명확하게 구사하세요.\n\n"
            
            "★ 실시간 발화 매너 심사 및 세션 제어 규칙 (인성 검증):\n"
            "1. 단순 STT 기계 오타는 문맥 보정 후 직무 질문 라인을 그대로 유지하되, 면접관을 향한 고의적인 비하, 조롱, 모욕, 혹은 한국어 비속어/욕설이 수신될 경우 이를 '기본 자질 미달의 결격 사유'로 엄격히 인지하십시오.\n"
            "2. (엄격한 실시간 질책 및 중단 규칙): 이러한 인성 결함이 포착될 경우, 다음 질문을 던지는 파이썬 흐름을 완전히 중단해야 합니다. "
            "지원자의 무례한 언행과 프로페셔널리즘 결여를 이성적이고 엄하게 지적하며 면접 강제 종료를 선언하는 대사를 구성하십시오. "
            "그 후 문장 맨 마지막에 반드시 '[면접 종료]'라는 토큰을 출력하여 시스템이 세션을 즉시 정지하고 성적표 모달로 넘어가도록 처리하십시오.\n\n"

            "★ 면접 진행 및 종료 자율 판단 규칙:\n"
            "제공된 전체 대화 이력(history)의 문맥적 흐름과 직무 답변의 깊이, 면접 지속 시간(턴 수)을 스스로 종합 평가하십시오.\n"
            "1. 해당 직무 역량에 대한 검증이 충분히 완료되었거나, 면접이 오랜 시간 밀도 있게 진행되어 클로징이 필요한 시점이라고 판단된다면 "
            "더 이상 추가 질문 없이 지원자의 노고를 치하하는 마무리 정리 멘트를 구사한 후, 문장 맨 마지막에 '[면접 종료]' 토큰을 명시하여 세션을 닫으십시오.\n"
            "2. 아직 직무 검증성 심사가 더 필요하다면 문맥을 이어받아 날카로운 다음 단계 면접 질문을 '딱 한 가지만' 연결하여 던지십시오. (이 경우 [면접 종료] 토큰 금지)\n\n"
            
            "★ 주의 규칙: 텍스트를 강조하기 위한 마크다운 특수 문법(**, *, __ 등) 및 불필요한 사족 설명은 완전히 배제하고, "
            "오직 일반 텍스트 문장과 마침표, 줄바꿈만 사용하여 실제 면접관의 완성형 대사체 구어문 형식으로만 출력하세요."
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        for turn in req.history:
            role = "assistant" if turn.get("role") == "interviewer" else "user"
            messages.append({"role": role, "content": turn.get("text", "")})
            
        response = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            temperature=0.6,
            max_tokens=512,
        )
        
        interviewer_reply = response.choices[0].message.content.strip()
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        
        return {
            "status": "success",
            "message": interviewer_reply,
            "latency_ms": elapsed_ms
        }

    print(f"[LLM] 면접 전면 종료 세션 - [대화 이력 전체 + 전 시간대 감정 통계] 결합 레포트 생성 개시")
    final_report_json = generate_comprehensive_report(req.job, req.history, req.emotion_timeline)
    final_report_json["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    print(f"[LLM] 종합 리포트 생성 완료 - 환산 점수: {final_report_json.get('overall_score')}/10")
    
    return final_report_json


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8003, reload=True)
