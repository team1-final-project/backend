import smtplib
from email.message import EmailMessage

from app.core.config import settings


def send_signup_verification_email(to_email: str, code: str) -> None:
    message = EmailMessage()
    message["Subject"] = "[Stocker] 이메일 인증코드"
    message["From"] = settings.smtp_from_email or settings.smtp_username
    message["To"] = to_email
    message.set_content(
        f"""안녕하세요.

Stocker 이메일 인증코드는 아래와 같습니다.

인증코드: {code}

인증코드는 {settings.email_code_expire_minutes}분 동안 유효합니다.
"""
    )

    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)