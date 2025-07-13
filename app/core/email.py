from typing import Any, Dict, Optional
import emails
from emails.template import JinjaTemplate
from app.core.config import settings

def send_email(
    email_to: str,
    subject: str,
    html_template: str,
    environment: dict[str, Any] = {},
    text_template: Optional[str] = None,
    headers: Dict[str, str] = None,
) -> None:
    """
    이메일 전송 함수
    """
    # 기본 헤더 설정
    default_headers = {
        "X-Priority": "1",  # 높은 우선순위 설정
        "X-MSMail-Priority": "High",
        "Importance": "High",
        "Reply-To": settings.EMAILS_FROM_EMAIL,
    }
    
    # 사용자 정의 헤더가 있으면 기본 헤더와 병합
    if headers:
        default_headers.update(headers)
    
    message = emails.Message(
        subject=subject,
        html=JinjaTemplate(html_template),
        mail_from=(settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL),
        headers=default_headers,
    )
    
    # 텍스트 버전의 이메일 추가 (멀티파트 이메일은 스팸 필터링 통과율 향상)
    if text_template:
        message.body = JinjaTemplate(text_template)
    
    smtp_options = {
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "user": settings.SMTP_USER,
        "password": settings.SMTP_PASSWORD,
        "tls": settings.SMTP_TLS,
    }
    
    response = message.send(
        to=email_to,
        render=environment,
        smtp=smtp_options,
    )
    
    return response

def send_reset_password_email(email_to: str, token: str) -> None:
    """
    비밀번호 재설정 이메일 전송
    """
    reset_link = f"{settings.FRONTEND_URL}/auth/reset-password?token={token}"
    
    subject = "Sungblab AI 비밀번호 재설정 안내"  # 스팸 표시어 '[' 제거
    
    html_template = """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2563eb; margin-bottom: 20px;">비밀번호 재설정 안내</h2>
            
            <p style="color: #374151; margin-bottom: 15px;">안녕하세요,</p>
            
            <p style="color: #374151; margin-bottom: 15px;">
                Sungblab AI 계정의 비밀번호 재설정을 요청하셨습니다.<br>
                아래 버튼을 클릭하여 새로운 비밀번호를 설정하실 수 있습니다.
            </p>
            
            <div style="margin: 30px 0;">
                <a href="{{ reset_link }}" 
                   style="background-color: #2563eb; 
                          color: white; 
                          padding: 12px 24px; 
                          text-decoration: none; 
                          border-radius: 6px;
                          display: inline-block;">
                    비밀번호 재설정하기
                </a>
            </div>
            
            <p style="color: #374151; margin-bottom: 15px;">
                이 링크는 24시간 동안 유효합니다.<br>
                비밀번호 재설정을 요청하지 않으셨다면 이 이메일을 무시하시면 됩니다.
            </p>
            
            <p style="color: #374151; margin-bottom: 15px;">
                감사합니다.<br>
                Sungblab AI 팀
            </p>
            
            <div style="margin-top: 30px; padding-top: 15px; border-top: 1px solid #e5e7eb;">
                <p style="color: #6b7280; font-size: 13px;">
                    본 메일은 발신 전용으로 회신이 불가합니다.<br>
                    © 2025 Sungblab AI. All rights reserved.
                </p>
            </div>
        </div>
    """
    
    # 텍스트 버전 이메일 템플릿 추가
    text_template = """
안녕하세요,

Sungblab AI 계정의 비밀번호 재설정을 요청하셨습니다.
아래 링크를 클릭하여 새로운 비밀번호를 설정하실 수 있습니다.

{{ reset_link }}

이 링크는 24시간 동안 유효합니다.
비밀번호 재설정을 요청하지 않으셨다면 이 이메일을 무시하시면 됩니다.

감사합니다.
Sungblab AI 팀

© 2024 Sungblab AI. All rights reserved.
    """
    
    # 커스텀 헤더 추가
    headers = {
        "List-Unsubscribe": f"<mailto:{settings.EMAILS_FROM_EMAIL}?subject=unsubscribe>",
        "X-Auto-Response-Suppress": "OOF, DR, RN, NRN, AutoReply"
    }
    
    send_email(
        email_to=email_to,
        subject=subject,
        html_template=html_template,
        text_template=text_template,
        environment={
            "reset_link": reset_link,
        },
        headers=headers,
    )

def send_verification_email(email_to: str, verification_code: str) -> None:
    """
    이메일 인증 코드 전송
    """
    subject = "Sungblab AI 인증 코드 안내"  # 스팸 표시어 '[' 제거
    
    # HTML 템플릿 - 불필요한 스타일링 최소화하고 간결하게 수정
    html_template = """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #2563eb; margin-bottom: 20px;">Sungblab AI 이메일 인증</h2>
            
            <p style="color: #374151; margin-bottom: 15px;">안녕하세요,</p>
            
            <p style="color: #374151; margin-bottom: 15px;">
                Sungblab AI 회원가입을 위한 인증 코드를 안내해 드립니다.<br>
                아래 코드를 입력하여 인증을 완료해 주세요.
            </p>
            
            <div style="margin: 30px 0; text-align: center;">
                <div style="background-color: #f3f4f6; 
                            padding: 15px; 
                            border-radius: 8px; 
                            font-size: 24px; 
                            font-weight: bold; 
                            letter-spacing: 3px;
                            color: #1f2937;
                            display: inline-block;">
                    {{ verification_code }}
                </div>
            </div>
            
            <p style="color: #374151; margin-bottom: 15px;">
                이 인증 코드는 10분 동안 유효합니다.<br>
                회원가입을 요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.
            </p>
            
            <p style="color: #374151; margin-bottom: 15px;">
                감사합니다.<br>
                Sungblab AI 팀
            </p>
            
            <div style="margin-top: 30px; padding-top: 15px; border-top: 1px solid #e5e7eb;">
                <p style="color: #6b7280; font-size: 13px;">
                    본 메일은 발신 전용으로 회신이 불가합니다.<br>
                    © 2025 Sungblab AI. All rights reserved.
                </p>
            </div>
        </div>
    """
    
    # 텍스트 버전 이메일 템플릿 추가 (멀티파트 이메일로 스팸 필터 회피 가능성 증가)
    text_template = """
안녕하세요,

Sungblab AI 회원가입을 위한 인증 코드를 안내해 드립니다.
아래 코드를 입력하여 인증을 완료해 주세요.

인증 코드: {{ verification_code }}

이 인증 코드는 10분 동안 유효합니다.
회원가입을 요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.

감사합니다.
Sungblab AI 팀

© 2025 Sungblab AI. All rights reserved.
    """
    
    # 커스텀 헤더 추가
    headers = {
        "List-Unsubscribe": f"<mailto:{settings.EMAILS_FROM_EMAIL}?subject=unsubscribe>",
        "X-Auto-Response-Suppress": "OOF, DR, RN, NRN, AutoReply"
    }
    
    send_email(
        email_to=email_to,
        subject=subject,
        html_template=html_template,
        text_template=text_template,
        environment={
            "verification_code": verification_code,
        },
        headers=headers,
    ) 