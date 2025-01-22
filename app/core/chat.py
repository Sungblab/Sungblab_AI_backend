from typing import List, Optional
from fastapi import UploadFile
import json
import anthropic
from anthropic import Anthropic
from app.core.config import settings
import base64

client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

async def get_chat_response(
    messages: List[dict],
    model: str,
    system_message: str,
    file: Optional[UploadFile] = None
):
    try:
        # 시스템 메시지를 첫 번째 메시지로 추가
        formatted_messages = []
        
        # 사용자 메시지 추가
        if file:
            file_content = await file.read()
            file_data = base64.b64encode(file_content).decode('utf-8')
            
            # 마지막 사용자 메시지에 파일 첨부
            if messages[-1]["role"] == "user":
                content = []
                if file.content_type.startswith("image/"):
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": file.content_type,
                            "data": file_data
                        }
                    })
                content.append({
                    "type": "text",
                    "text": messages[-1]["content"]
                })
                messages[-1]["content"] = content

        # Claude API 호출
        response = client.messages.create(
            model=model,
            system=system_message,
            messages=messages,
            max_tokens=2048,
            temperature=0.7,
            stream=True
        )

        for chunk in response:
            if chunk.type == "content_block_delta":
                response = {"content": chunk.delta.text}
                yield f"data: {json.dumps(response)}\n\n"

    except Exception as e:
        error_response = {"error": str(e)}
        yield f"data: {json.dumps(error_response)}\n\n" 