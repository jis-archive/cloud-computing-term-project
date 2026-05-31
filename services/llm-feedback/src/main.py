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


FEEDBACK_SYSTEM_PROMPT = """
당신은 취업 면접 전문 코치입니다.
지원자의 면접 발화 내용과 감정 분석 결과를 종합하여 구체적이고 실질적인 피드백을 제공합니다.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "overall_score": <종합 점수 1-10>,
  "speech_feedback": {
    "summary": "<발화 내용 요약 1-2문장>",
    "strengths": ["<잘한 점 1>", "<잘한 점 2>"],
    "improvements": ["<개선점 1>", "<개선점 2>"],
    "better_expressions": ["<더 나은 표현 예시 1>", "<더 나은 표현 예시 2>"]
  },
  "emotion_feedback": {
    "assessment": "<감정 분석 결과 해석 1-2문장>",
    "tips": ["<태도 개선 팁 1>", "<태도 개선 팁 2>"]
  },
  "overall_feedback": "<종합 격려 피드백 2-3문장>"
}
"""


def generate_feedback(stt: dict, emotion: dict) -> dict:
    user_message = f"""
면접 분석 결과를 종합하여 피드백을 제공해주세요.

[전체 발화 내용]
{stt.get("text", "(발화 없음)")}
발화 시간: {stt.get("duration", 0)}초

[감정 분석 평균]
- 자신감: {emotion.get("confidence", 0)}점
- 긴장도: {emotion.get("tension", 0)}점
- 안정도: {emotion.get("stability", 0)}점
"""

    response = groq_client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": FEEDBACK_SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
        temperature=0.4,
        max_tokens=1024,
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
            "가벼운 반응(Reaction)을 1~2문장으로 먼저 명확하게 구사하세요.\n"
            
            # ◀ [핵심 추가] 면접 분량 및 종료 조건 프롬프트 제약 사항 수립
            f"★ 면접 분량 제어 및 종료 규칙:\n"
            f"1. 대화 이력(history)의 총 원소 개수가 {total_turns}개에 도달했습니다. "
            f"질문과 답변이 충분히 오고 갔다고 판단되거나 혹은 시간이 너무 오래되었다면, "
            f"더 이상 다음 질문을 던지지 말고 지원자의 노고를 격려하며 면접을 최종 정리하는 멘트로 마무리하세요.\n"
            f"2. 면접을 완전히 종료할 때에는 문장의 맨 마지막에 반드시 '[면접 종료]'라는 정확한 핵심 텍스트 토큰을 명시하십시오.\n"
            f"3. 아직 검증이 더 필요하다고 판단된다면, 이전 맥락을 이어받아 직무 전문성을 깊이 파고드는 다음 질문을 '딱 한 가지만' 연결하여 질문하십시오.\n"
            
            "★ 주의 규칙: 마크다운 가독성 문법(**, *, # 등) 및 군더더기 사족은 완전히 배제하고, "
            "오직 텍스트 문장과 마침표, 줄바꿈만 사용하여 실제 면접관의 완성형 대사체 구어문 형식으로만 출력하세요."
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

    print(f"[LLM] 면접 종료 세션 - 종합 분석 피드백 생성 요청 수신")
    print(f"req.stt_result: {req.stt_result}")
    print(f"req.emotion_result: {req.emotion_result}")
    
    result = generate_feedback(req.stt_result, req.emotion_result)
    result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    print(f"[LLM] 피드백 생성 완료 - 점수: {result.get('overall_score')}/10")
    return result


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8003, reload=True)
