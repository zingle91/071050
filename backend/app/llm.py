"""LLM provider interface — mock by default when no API key is set."""
from app.config import settings


async def generate_reply(user_message: str, room_name: str = "") -> str:
    """Return an AI reply. Uses mock when LLM_API_KEY is empty."""
    if not settings.llm_api_key:
        return _mock_reply(user_message, room_name)

    try:
        import httpx

        base = settings.llm_api_base or "https://api.openai.com/v1"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "당신은 회사 메신저의 AI 도우미입니다. "
                                "한국어로 간단하고 친절하게 답변하세요."
                            ),
                        },
                        {"role": "user", "content": user_message},
                    ],
                    "max_tokens": 300,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return f"(LLM 오류, mock으로 전환) {_mock_reply(user_message, room_name)} [{exc}]"


def _mock_reply(user_message: str, room_name: str = "") -> str:
    msg = user_message.lower().strip()
    if any(k in msg for k in ("안녕", "hello", "hi", "헬로")):
        return "안녕하세요! 저는 회사 AI 봇입니다. 무엇을 도와드릴까요?"
    if any(k in msg for k in ("도움", "help", "기능")):
        return (
            "저는 채팅방에서 간단한 질문에 답할 수 있습니다. "
            "쪽지(비동기 쪽지), 1:1/그룹 채팅도 함께 이용해 보세요."
        )
    if any(k in msg for k in ("시간", "날짜", "today")):
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"현재 시각은 {now} 입니다. (mock LLM)"
    if any(k in msg for k in ("부서", "조직", "사번")):
        return (
            "조직 정보는 좌측 '조직도' 메뉴에서 확인할 수 있습니다. "
            "데모 계정 사번: F00001~F00010, 비밀번호: 1q2w3e1!"
        )
    room_hint = f" ({room_name})" if room_name else ""
    return (
        f"[AI 봇 응답{room_hint}] '{user_message}'에 대해 생각해 봤어요. "
        "지금은 mock LLM 모드입니다. LLM_API_KEY를 설정하면 실제 모델을 사용합니다."
    )
