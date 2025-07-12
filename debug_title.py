import asyncio
import sys
sys.path.append("/app")

async def test():
    from app.api.api_v1.endpoints.chat import generate_chat_room_name
    result = await generate_chat_room_name("파이썬 리스트 사용법 알려주세요")
    print(f"Generated title: {result}")

asyncio.run(test())