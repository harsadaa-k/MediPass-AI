"""
Outgoing email (verification and password-reset links) over SMTP.

send_email() returns True/False instead of swallowing errors, so callers can
tell the user when a link couldn't be sent (and offer "Resend"). Messages
carry a plain-text part, a display name, Date and Message-ID headers --
HTML-only mail without them is much more likely to land in spam.

Links point at MEDIPASS_FRONTEND_URL (default http://localhost:5173), so a
deployed app sends links to its real address.
"""
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid


EMAIL_LOG = os.environ.get("MEDIPASS_EMAIL_LOG", os.path.join(os.path.dirname(__file__), "..", "logs", "email.log"))


def _log(to_email: str, subject: str, outcome: str) -> None:
    """One line per send attempt, so delivery problems can be checked without
    the server console (backend/logs/email.log; never contains the link)."""
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {outcome:<8} to={to_email}  subject={subject!r}"
    print(f"EMAIL {line}")
    try:
        os.makedirs(os.path.dirname(EMAIL_LOG), exist_ok=True)
        with open(EMAIL_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def frontend_url() -> str:
    return os.environ.get("MEDIPASS_FRONTEND_URL", "http://localhost:5173").rstrip("/")


def send_email(to_email: str, subject: str, html_body: str, text_body: str = "") -> bool:
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not smtp_username or not smtp_password:
        print("WARNING: SMTP credentials not set in .env. Mocking email to console:")
        print(f"TO: {to_email}")
        print(f"SUBJECT: {subject}")
        print(f"BODY:\n{text_body or html_body}")
        return True  # dev mode: the console is the mailbox

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((os.environ.get("SMTP_FROM_NAME", "MediPass"), smtp_username))
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=smtp_username.split("@")[-1])
    if text_body:
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            refused = server.sendmail(smtp_username, [to_email], msg.as_string())
        if refused:
            _log(to_email, subject, f"REFUSED {refused}")
            return False
        _log(to_email, subject, "SENT")
        return True
    except Exception as e:
        _log(to_email, subject, f"FAILED {type(e).__name__}: {str(e)[:200]}")
        return False


def _link_email(title: str, intro: str, button: str, url: str, footer: str = ""):
    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #1c2733;">
        <h2 style="color: #16365f;">{title}</h2>
        <p>{intro}</p>
        <p><a href="{url}" style="background:#0e8a8c;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none;">{button}</a></p>
        <p>Or paste this link into your browser:<br>{url}</p>
        {f"<p>{footer}</p>" if footer else ""}
      </body>
    </html>
    """
    text = f"{title}\n\n{intro}\n\n{button}: {url}\n" + (f"\n{footer}\n" if footer else "")
    return html, text


def send_verification_email(to_email: str, token: str) -> bool:
    url = f"{frontend_url()}/verify-email?token={token}"
    html, text = _link_email(
        "Welcome to MediPass!", "Please verify your email address to activate your account.",
        "Verify email", url, "If you didn't create a MediPass account, you can ignore this email.")
    return send_email(to_email, "Verify your MediPass account", html, text)


def send_reset_password_email(to_email: str, token: str) -> bool:
    url = f"{frontend_url()}/reset-password?token={token}"
    html, text = _link_email(
        "MediPass password reset", "We received a request to reset your password.",
        "Reset password", url, "If you did not request this, you can safely ignore this email.")
    return send_email(to_email, "Reset your MediPass password", html, text)
