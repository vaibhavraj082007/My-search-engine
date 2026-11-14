"""Email delivery for 8search (password resets, sign-in alerts and feedback).

Configuration is read from environment variables or a ``.env`` file in the
project root / ``backend/`` directory:

    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=you@gmail.com
    SMTP_PASSWORD=your-app-password
    SMTP_FROM="8search <you@gmail.com>"
    SMTP_SECURITY=starttls          # starttls | ssl | none
    APP_BASE_URL=http://localhost:8000
    FEEDBACK_EMAIL=you@gmail.com    # where feedback submissions are sent

When SMTP is not configured, emails (including password-reset links) are
printed to the server console so local development still works.
"""

import html
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger("8search.email")

_ROOT = Path(__file__).resolve().parent.parent
for _env_file in (_ROOT / ".env", _ROOT / "backend" / ".env"):
    if _env_file.exists():
        load_dotenv(_env_file, override=False)


def app_base_url() -> str:
    """Base URL used to build links inside emails."""
    return os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")


def feedback_email() -> str:
    """Inbox that receives website feedback submissions."""
    return os.getenv("FEEDBACK_EMAIL", "vaibhavtripathi589@gmail.com").strip()


def _header_safe(value: str, limit: int = 200) -> str:
    """Keep user-controlled values from injecting extra email headers."""
    return " ".join(str(value).splitlines()).strip()[:limit]


def _smtp_config() -> dict:
    user = os.getenv("SMTP_USER", "").strip()
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": user,
        "password": os.getenv("SMTP_PASSWORD", "").strip(),
        "sender": os.getenv("SMTP_FROM", "").strip() or user,
        "security": os.getenv("SMTP_SECURITY", "starttls").strip().lower(),
    }


def is_configured() -> bool:
    """True when enough SMTP settings exist to attempt delivery."""
    cfg = _smtp_config()
    return bool(cfg["host"] and cfg["user"] and cfg["password"] and cfg["sender"])


def send_email(
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """Send an email. Returns True on success, False otherwise.

    Delivery failures are logged and never raised, so they can safely run as
    FastAPI background tasks without breaking the request.
    """
    cfg = _smtp_config()
    subject = _header_safe(subject)
    to_email = _header_safe(to_email)
    reply_to = _header_safe(reply_to) if reply_to else None

    if not is_configured():
        logger.warning("SMTP not configured; email to %s was not sent", to_email)
        print(
            "\n─── 8search email (SMTP not configured) ─────────────────────\n"
            f"To: {to_email}\n"
            + (f"Reply-To: {reply_to}\n" if reply_to else "")
            + f"Subject: {subject}\n\n"
            f"{text_body}\n"
            "─────────────────────────────────────────────────────────────\n",
            flush=True,
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    msg["To"] = to_email
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        if cfg["security"] == "ssl":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15, context=context) as smtp:
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as smtp:
                smtp.ehlo()
                if cfg["security"] == "starttls":
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
        logger.info("Sent email to %s: %s", to_email, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_email)
        print(f"[8search email] Failed to send '{subject}' to {to_email}", flush=True)
        return False


def send_password_reset(to_email: str, reset_url: str, ttl_minutes: int = 30) -> bool:
    """Send the password-reset link."""
    subject = "Reset your 8search password"
    text_body = (
        "Hello,\n\n"
        "We received a request to reset the password for your 8search account.\n\n"
        f"Open this link to choose a new password (valid for {ttl_minutes} minutes):\n"
        f"{reset_url}\n\n"
        "If you didn't request this, you can safely ignore this email — "
        "your password will not change.\n"
    )
    safe_url = html.escape(reset_url, quote=True)
    html_body = f"""\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#0a0a0a;font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#111111;border:1px solid #2a2a2a;border-radius:12px;padding:32px;">
            <tr>
              <td style="color:#00e676;font-size:26px;font-weight:800;padding-bottom:16px;">8search</td>
            </tr>
            <tr>
              <td style="color:#e0e0e0;font-size:16px;line-height:1.6;">
                <p style="margin:0 0 12px;">Hello,</p>
                <p style="margin:0 0 20px;">
                  We received a request to reset the password for your 8search account.
                </p>
                <p style="margin:0 0 24px;">
                  <a href="{safe_url}"
                     style="display:inline-block;background:#00e676;color:#000000;font-weight:700;text-decoration:none;padding:12px 22px;border-radius:6px;">
                    Choose a new password
                  </a>
                </p>
                <p style="margin:0 0 12px;color:#9e9e9e;font-size:14px;">
                  This link is valid for {ttl_minutes} minutes. If the button doesn't work,
                  copy and paste this URL into your browser:
                </p>
                <p style="margin:0 0 20px;font-size:13px;word-break:break-all;">
                  <a href="{safe_url}" style="color:#69f0ae;">{safe_url}</a>
                </p>
                <p style="margin:0;color:#9e9e9e;font-size:14px;">
                  If you didn't request this, you can safely ignore this email — your password will not change.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return send_email(to_email, subject, text_body, html_body)


def send_login_notice(to_email: str, when: str, ip_address: str, user_agent: str) -> bool:
    """Send a security notice after a successful sign-in."""
    subject = "Security alert: new sign-in to your 8search account"
    reset_link = f"{app_base_url()}/forgot-password.html"
    text_body = (
        "Hello,\n\n"
        f"Your 8search account ({to_email}) was just signed in to.\n\n"
        f"Time: {when}\n"
        f"IP address: {ip_address}\n"
        f"Device: {user_agent}\n\n"
        "If this was you, no action is needed.\n\n"
        "If you don't recognize this activity, your account may be at risk.\n"
        "Reset your password immediately:\n"
        f"{reset_link}\n\n"
        "You can also reply to this email to report the sign-in to the 8search team.\n"
    )
    safe_email = html.escape(to_email)
    safe_when = html.escape(when)
    safe_ip = html.escape(ip_address)
    safe_ua = html.escape(user_agent)
    safe_link = html.escape(reset_link, quote=True)
    html_body = f"""\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#0a0a0a;font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#111111;border:1px solid #2a2a2a;border-radius:12px;padding:32px;">
            <tr>
              <td style="color:#00e676;font-size:26px;font-weight:800;padding-bottom:16px;">8search</td>
            </tr>
            <tr>
              <td style="color:#e0e0e0;font-size:16px;line-height:1.6;">
                <p style="margin:0 0 12px;">Hello,</p>
                <p style="margin:0 0 20px;">
                  Your 8search account (<strong>{safe_email}</strong>) was just signed in to.
                </p>
                <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;margin:0 0 20px;background:#151515;border:1px solid #2a2a2a;border-radius:8px;">
                  <tr>
                    <td style="padding:14px 16px;color:#9e9e9e;font-size:14px;line-height:1.7;">
                      <strong style="color:#e0e0e0;">Time:</strong> {safe_when}<br>
                      <strong style="color:#e0e0e0;">IP address:</strong> {safe_ip}<br>
                      <strong style="color:#e0e0e0;">Device:</strong> {safe_ua}
                    </td>
                  </tr>
                </table>
                <p style="margin:0 0 12px;">
                  If this was you, no action is needed.
                </p>
                <p style="margin:0 0 20px;color:#9e9e9e;font-size:14px;">
                  If you don't recognize this activity, your account may be at risk.
                  Reset your password immediately.
                </p>
                <p style="margin:0 0 18px;">
                  <a href="{safe_link}"
                     style="display:inline-block;background:#00e676;color:#000000;font-weight:700;text-decoration:none;padding:12px 22px;border-radius:6px;">
                    Reset password
                  </a>
                </p>
                <p style="margin:0;color:#9e9e9e;font-size:13px;">
                  You can also reply to this email to report the sign-in to the 8search team.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return send_email(to_email, subject, text_body, html_body)


def send_feedback_notice(
    feedback_id: int,
    name: str,
    email: str,
    message: str,
    when: str,
    ip_address: str,
    user_agent: str,
) -> bool:
    """Email a website feedback submission to the site owner."""
    owner = feedback_email()
    if not owner:
        logger.warning("FEEDBACK_EMAIL is not set; feedback #%s was stored only", feedback_id)
        return False

    if name and email:
        sender = f"{name} <{email}>"
    else:
        sender = name or email or "Anonymous visitor"

    subject = f"New 8search feedback from {_header_safe(sender, 80)}"
    text_body = (
        "Hello,\n\n"
        "A new feedback message was submitted through 8search.\n\n"
        f"Feedback ID: #{feedback_id}\n"
        f"From: {sender}\n"
        f"Time: {when}\n"
        f"IP address: {ip_address}\n"
        f"Device: {user_agent}\n\n"
        "Message:\n"
        "------------------------------------------------------------\n"
        f"{message}\n"
        "------------------------------------------------------------\n\n"
        "Reply directly to this email to respond to the visitor.\n"
    )

    safe_id = html.escape(str(feedback_id))
    safe_sender = html.escape(sender)
    safe_when = html.escape(when)
    safe_ip = html.escape(ip_address)
    safe_ua = html.escape(user_agent)
    safe_message = html.escape(message)

    html_body = f"""\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#0a0a0a;font-family:Arial,Helvetica,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0a0a0a;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#111111;border:1px solid #2a2a2a;border-radius:12px;padding:32px;">
            <tr>
              <td style="color:#00e676;font-size:26px;font-weight:800;padding-bottom:6px;">8search</td>
            </tr>
            <tr>
              <td style="color:#9e9e9e;font-size:13px;padding-bottom:22px;">
                New feedback from the website
              </td>
            </tr>
            <tr>
              <td style="color:#e0e0e0;font-size:16px;line-height:1.6;">
                <p style="margin:0 0 18px;">
                  You received a new feedback message (ID <strong>#{safe_id}</strong>).
                </p>
                <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;margin:0 0 20px;background:#151515;border:1px solid #2a2a2a;border-radius:8px;">
                  <tr>
                    <td style="padding:14px 16px;color:#9e9e9e;font-size:14px;line-height:1.7;">
                      <strong style="color:#e0e0e0;">From:</strong> {safe_sender}<br>
                      <strong style="color:#e0e0e0;">Time:</strong> {safe_when}<br>
                      <strong style="color:#e0e0e0;">IP address:</strong> {safe_ip}<br>
                      <strong style="color:#e0e0e0;">Device:</strong> {safe_ua}
                    </td>
                  </tr>
                </table>
                <p style="margin:0 0 8px;color:#9e9e9e;font-size:13px;text-transform:uppercase;letter-spacing:0.08em;">
                  Message
                </p>
                <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;margin:0 0 20px;background:#151515;border-left:3px solid #00e676;border-radius:6px;">
                  <tr>
                    <td style="padding:16px;color:#e0e0e0;font-size:15px;line-height:1.7;white-space:pre-wrap;">{safe_message}</td>
                  </tr>
                </table>
                <p style="margin:0;color:#9e9e9e;font-size:13px;">
                  Reply directly to this email to respond to the visitor.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return send_email(owner, subject, text_body, html_body, reply_to=email or None)
