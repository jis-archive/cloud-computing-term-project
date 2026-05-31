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


class FeedbackRequest(BaseModel):
    stt_result: dict = {}
    emotion_result: dict = {}
    is_start: bool = False
    is_chat_turn: bool = False
    job: str = "개발자"
    history: list = []
    emotion_timeline: dict = {}


FEEDBACK_SYSTEM_PROMPT = """
당신은 대한민국 최고 수준의 기업 인사팀 핵심 임원이자 취업 면접 전문 수석 코치입니다.
지정된 직종(job)에 맞게 지원자가 수행한 전체 대화 내용과 실시간 감정 타임라인 데이터를 종합 입체 심사하여 피드백 보고서를 발행해야 합니다.

전체 대화 배열(history) 내의 면접관 질문 의도를 지원자가 얼마나 정확히 파악했는지, 답변 구조의 논리성이 우수했는지 다각도로 검토하고,
동시에 전달된 전체 시간대 감정 통계 수치(confidence, tension, stability)의 흐름과 평균값을 바탕으로 압박 상황에서의 태도 제어 능력을 과학적으로 채점하세요.

반드시 아래 지정된 JSON 형식으로만 완벽한 순수 객체 구조로 응답하세요:
{
  "overall_score": <종합 점수 1-10 사이 정수>,
  "speech_feedback": {
    "summary": "<지원자의 전체 발화 핵심 내용 요약 및 직무 적합도 총평 1-2문장>",
    "strengths": ["<대화 이력 분석 기준 구체적인 논리적 장점 1>", "<답변 내용상 우수했던 점 2>"],
    "improvements": ["<질문 의도에서 벗어났거나 논리가 빈약했던 부분 개선점 1>", "<내용 보완점 2>"],
    "better_expressions": ["<더 전문적이고 신뢰감 있게 바꾼 더 나은 대안 답변 표현 예시 문장 1>", "<대안 예시 문장 2>"]
  },
  "emotion_feedback": {
    "assessment": "<감정 평균 수치 및 타임라인 변화 추이를 바탕으로 해석한 심리/태도 분석 1-2문장>",
    "tips": ["<면접 중 긴장 수치 완화 및 자신감 표출을 위한 맞춤형 비언어 태도 팁 1>", "<태도 교정 팁 2>"]
  },
  "overall_feedback": "<지원자의 잠재력을 격려하고 직무 역량 성장을 독려하는 따뜻한 종합 격려 피드백 2-3문장>"
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
* 참고:자신감과 안정도가 높을수록 우수하며, 긴장도가 높을수록 페이스 조절이 필요했음을 뜻합니다.

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


@app.post("/feedback")
async def create_feedback(req: FeedbackRequest):
    print(f"[LLM] 피드백 생성 요청 수신")

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
        
        return {
            "status": "success",
            "message": opening_question,
            "latency_ms": elapsed_ms
        }
    
    if req.is_chat_turn:
        print(f"[LLM] 실시간 턴제 소통 가동 (수신된 세션 총 턴 수: {len(req.history)})")

        total_turns = len(req.history)
        
        system_prompt = (
            f"당신은 현재 [{req.job}] 직무 역량을 심사 중인 전문적이고 예리한 AI 면접관입니다. "
            "지원자가 직전에 제출한 마지막 답변을 주의 깊게 읽고, 면접관으로서 지적이고 공감 어리거나 혹은 보완점을 짚어주는 "
            "가벼운 반응(Reaction)을 1~2문장으로 명확하게 구사하세요.\n\n"
            
            "★ 면접 진행 및 종료 자율 판단 규칙 (중요):\n"
            "제공된 전체 대화 이력(history)의 문맥적 흐름과 답변의 깊이, 면접 지속 시간을 스스로 종합 평가하십시오.\n"
            "1. 만약 해당 직무 역량에 대한 검증이 충분히 완료되었거나, 면접이 충분히 오래 진행되어 마무리할 시점이라고 판단된다면, "
            "더 이상 추가 질문을 던지지 말고 지원자의 노고를 치하하는 지적이고 따뜻한 마무리 정리 멘트를 구사하십시오. "
            "이 경우, 반드시 문장의 맨 마지막에 '[면접 종료]'라는 정확한 핵심 토큰을 명시하여 면접 세션을 최종 완료해야 합니다.\n"
            "2. 아직 검증이 더 필요하거나 꼬리 질문을 통해 지원자의 고유 역량을 심층 분석해야 한다면, 이전 문맥을 이어받아 "
            "날카로운 다음 단계 면접 질문을 '딱 한 가지만' 자연스럽게 연결하여 던지십시오. 이 경우에는 절대로 '[면접 종료]' 토큰을 출력하면 안 됩니다.\n\n"
            
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
