import asyncio
import sys
import logging
sys.path.append('/app')

# 로깅 설정
logging.basicConfig(level=logging.INFO)

async def test_ai_response():
    from app.api.api_v1.endpoints.chat import get_gemini_client
    from google.genai import types
    import json
    import re
    
    client = get_gemini_client()
    
    prompt_template = '''Create a short Korean title (3-5 words) with emoji for this message. Return only JSON format: {"title": "..."}

Examples:
{"title": "📚 파이썬 공부"}
{"title": "🍕 요리 질문"}

Message: 파이썬 사용법 알려줘'''
    
    print(f'Testing with prompt:\n{prompt_template}')
    print('---')
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[prompt_template],
        config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=100)
    )
    
    print(f'Raw response: {repr(response.text)}')
    
    if response.text:
        text = response.text.strip()
        print(f'Stripped text: {repr(text)}')
        
        # 마크다운 코드 블록 제거
        if text.startswith('```'):
            print('Found markdown code block, extracting...')
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if match:
                text = match.group(1).strip()
                print(f'Extracted JSON: {repr(text)}')
        
        try:
            result = json.loads(text)
            print(f'Successfully parsed JSON: {result}')
            if 'title' in result:
                print(f'Found title: {result["title"]}')
            else:
                print('No title key found in JSON')
        except json.JSONDecodeError as e:
            print(f'JSON parse error: {e}')
            print('Trying to fix the JSON...')
            # JSON 수정 시도
            if '"title"' in text:
                try:
                    # 간단한 JSON 추출 시도
                    import re
                    title_match = re.search(r'"title":\s*"([^"]*)"', text)
                    if title_match:
                        extracted_title = title_match.group(1)
                        print(f'Extracted title from regex: {extracted_title}')
                except Exception as e2:
                    print(f'Regex extraction failed: {e2}')
    else:
        print('No text in response')

if __name__ == "__main__":
    asyncio.run(test_ai_response())