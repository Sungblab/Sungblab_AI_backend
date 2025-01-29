from typing import Optional
import httpx
from app.core.config import settings
from app.schemas.auth import GoogleUser

async def verify_google_token(token: str) -> Optional[GoogleUser]:
    try:
        async with httpx.AsyncClient() as client:
            # Google OAuth2 userinfo 엔드포인트로 요청
            response = await client.get(
                'https://www.googleapis.com/oauth2/v3/userinfo',
                headers={'Authorization': f'Bearer {token}'}
            )
            
            if response.status_code != 200:
                return None
                
            userinfo = response.json()
            
            return GoogleUser(
                email=userinfo['email'],
                name=userinfo['name'],
                picture=userinfo.get('picture'),
                sub=userinfo['sub']
            )
    except Exception as e:
        return None 