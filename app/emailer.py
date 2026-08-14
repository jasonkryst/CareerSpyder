import smtplib
from email.mime.text import MIMEText


def send_email(smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str,
                email_from: str, email_to: list[str], subject: str, html_body: str) -> None:
    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = ", ".join(email_to)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(email_from, email_to, msg.as_string())
