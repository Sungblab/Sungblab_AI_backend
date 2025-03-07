from typing import List, Optional
from fastapi import UploadFile
import json
import anthropic
from anthropic import Anthropic
from app.core.config import settings
import base64
import httpx

client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

async def get_chat_response(
    messages: List[dict],
    model: str,
    system_message: str,
    file: Optional[UploadFile] = None
):
    try:
        if model in ["sonar", "sonar-pro"]:
            # Sonar API 호출
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={"Authorization": f"Bearer {settings.SONAR_API_KEY}"},
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": True
                    }
                )
                
                if response.status_code != 200:
                    error_response = {"error": f"Sonar API error: {response.status_code}"}
                    yield f"data: {json.dumps(error_response)}\n\n"
                    return

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if "choices" in data and data["choices"]:
                                choice = data["choices"][0]
                                if "delta" in choice:
                                    delta = choice["delta"]
                                    if "content" in delta:
                                        yield f"data: {json.dumps({'content': delta['content']})}\n\n"
                                    if "citations" in delta:
                                        yield f"data: {json.dumps({'citations': delta['citations']})}\n\n"
                                elif "citations" in choice:
                                    yield f"data: {json.dumps({'citations': choice['citations']})}\n\n"
                        except json.JSONDecodeError:
                            continue
                return

        # Claude API 처리
        formatted_messages = []
        
        if file:
            file_content = await file.read()
            file_data = base64.b64encode(file_content).decode('utf-8')
            
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

        response = client.messages.create(
            model=model,
            system=system_message,
            messages=messages,
            max_tokens=8192,
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