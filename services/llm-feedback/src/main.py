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
    job: str = "개발자"


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
            "당신은 대기업 인사팀 출신의 베테랑 AI 면접관입니다. "
            "지원자가 선택한 직종 컨텍스트에 완벽하게 몰입하여, 지적이고 신뢰감 주는 첫 인사말을 건네세요. "
            "그 직후 해당 직무의 전문성을 검증할 수 있는 날카롭고 참신한 첫 번째 면접 질문을 딱 '하나'만 명확하게 제시하세요. "
            "주의: 시스템 설명조의 군더더기 문장이나 사족은 완전히 배제하고, 실제 면접관의 대사만 자연스럽게 출력하세요."
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
