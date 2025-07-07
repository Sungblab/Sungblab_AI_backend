from typing import List, Optional
from fastapi import UploadFile
import json
from app.core.config import settings
import base64
import google.generativeai as genai

def get_gemini_client():
    """Gemini 클라이언트를 생성하는 함수"""
    try:
        if not settings.GEMINI_API_KEY:
            return None
        
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-pro')
        return model
    except Exception as e:
        print(f"Gemini client creation error: {e}")
        return None

async def get_chat_response(
    messages: List[dict],
    model: str,
    system_message: str,
    file: Optional[UploadFile] = None
):
    try:
        # Gemini 클라이언트 가져오기
        gemini_model = get_gemini_client()
        if not gemini_model:
            error_response = {"error": "Gemini API key is not configured"}
            yield f"data: {json.dumps(error_response)}\n\n"
            return

        # 메시지 포맷팅
        conversation_text = ""
        for message in messages:
            role_text = "Human" if message["role"] == "user" else "Assistant"
            conversation_text += f"{role_text}: {message['content']}\n"

        # 시스템 프롬프트 추가
        full_prompt = f"{system_message}\n\n{conversation_text}\nAssistant:"

        # 파일 처리
        content_parts = [full_prompt]
        if file:
            file_content = await file.read()
            file_data = base64.b64encode(file_content).decode('utf-8')
            
            if file.content_type.startswith("image/"):
                # 이미지 파일 처리는 추후 구현
                content_parts.append(f"[이미지 파일: {file.filename}]")

        # 생성 설정
        generation_config = genai.types.GenerationConfig(
            temperature=0.7,
            top_p=0.95,
            top_k=40,
            max_output_tokens=8192,
        )

        # 스트리밍 응답 생성
        response = gemini_model.generate_content(
            content_parts,
            generation_config=generation_config,
            stream=True
        )

        for chunk in response:
            if chunk.text:
                response_data = {"content": chunk.text}
                yield f"data: {json.dumps(response_data)}\n\n"

    except Exception as e:
        error_response = {"error": str(e)}
        yield f"data: {json.dumps(error_response)}\n\n" 