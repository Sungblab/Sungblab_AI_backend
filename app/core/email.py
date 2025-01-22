from typing import Any
import emails
from emails.template import JinjaTemplate
from app.core.config import settings

def send_email(
    email_to: str,
    subject: str,
    html_template: str,
    environment: dict[str, Any] = {},
) -> None:
    """
    이메일 전송 함수
    """
    message = emails.Message(
        subject=subject,
        html=JinjaTemplate(html_template),
        mail_from=(settings.EMAILS_FROM_NAME, settings.EMAILS_FROM_EMAIL),
    )
    
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
    
    subject = "[Sungblab AI] 비밀번호 재설정 안내"
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
            
            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb;">
                <p style="color: #6b7280; font-size: 14px;">
                    본 메일은 발신 전용으로 회신이 불가능합니다.<br>
                    문의사항이 있으시면 고객센터를 이용해 주시기 바랍니다.
                </p>
            </div>
        </div>
    """
    
    send_email(
        email_to=email_to,
        subject=subject,
        html_template=html_template,
        environment={
            "reset_link": reset_link,
        },
    ) 