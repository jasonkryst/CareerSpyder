import smtplib
from email.mime.text import MIMEText

# Port 465 uses implicit TLS (SMTP_SSL) — the connection is encrypted from
# the first byte. Every other port uses STARTTLS, which upgrades a plain
# connection after the initial greeting. The two protocols are
# mutually incompatible: sending a STARTTLS upgrade on port 465 would get
# an SSL handshake error because the server expects a ClientHello immediately.
_IMPLICIT_TLS_PORT = 465


def send_email(smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str,
                email_from: str, email_to: list[str], subject: str, html_body: str) -> None:
    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = ", ".join(email_to)

    if smtp_port == _IMPLICIT_TLS_PORT:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(smtp_user, smtp_password)
            server.sendmail(email_from, email_to, msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(email_from, email_to, msg.as_string())
