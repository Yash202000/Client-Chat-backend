"""
Email Service
Handles sending emails via SMTP
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any
from app.core.config import settings


async def send_email_smtp(
    to_email: str,
    subject: str,
    html_content: Optional[str] = None,
    text_content: Optional[str] = None,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None,
    smtp_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Send email using SMTP

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML email body (optional)
        text_content: Plain text email body (optional)
        from_email: Sender email (defaults to settings)
        from_name: Sender name (defaults to settings)
        smtp_config: Optional SMTP configuration override

    Returns:
        Dict with message_id and status
    """
    # Use provided config or fall back to settings
    if smtp_config:
        smtp_host = smtp_config.get('host', settings.SMTP_HOST)
        smtp_port = smtp_config.get('port', settings.SMTP_PORT)
        smtp_user = smtp_config.get('user', settings.SMTP_USER)
        smtp_password = smtp_config.get('password', settings.SMTP_PASSWORD)
        smtp_use_tls = smtp_config.get('use_tls', settings.SMTP_USE_TLS)
    else:
        smtp_host = settings.SMTP_HOST
        smtp_port = settings.SMTP_PORT
        smtp_user = settings.SMTP_USER
        smtp_password = settings.SMTP_PASSWORD
        smtp_use_tls = settings.SMTP_USE_TLS

    # Validate SMTP configuration
    if not all([smtp_host, smtp_port, smtp_user, smtp_password]):
        raise ValueError("SMTP credentials are not configured. Please set SMTP_HOST, SMTP_PORT, SMTP_USER, and SMTP_PASSWORD in settings.")

    # Set from email and name
    if not from_email:
        from_email = getattr(settings, 'SMTP_FROM_EMAIL', smtp_user)
    if not from_name:
        from_name = getattr(settings, 'SMTP_FROM_NAME', 'AgentConnect')

    # Create message
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f"{from_name} <{from_email}>"
    msg['To'] = to_email

    # Add plain text part if provided
    if text_content:
        text_part = MIMEText(text_content, 'plain')
        msg.attach(text_part)

    # Add HTML part if provided
    if html_content:
        html_part = MIMEText(html_content, 'html')
        msg.attach(html_part)

    # If neither is provided, raise error
    if not text_content and not html_content:
        raise ValueError("Either text_content or html_content must be provided")

    try:
        # Connect to SMTP server
        if smtp_use_tls:
            server = smtplib.SMTP(smtp_host, smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port)

        # Login
        server.login(smtp_user, smtp_password)

        # Send email
        server.send_message(msg)

        # Close connection
        server.quit()

        print(f"[EMAIL SERVICE] Successfully sent email to {to_email}")

        return {
            "message_id": msg['Message-ID'] if 'Message-ID' in msg else None,
            "status": "sent",
            "to": to_email,
            "subject": subject
        }

    except smtplib.SMTPAuthenticationError as e:
        print(f"[EMAIL SERVICE] SMTP Authentication failed: {e}")
        raise ValueError(f"SMTP authentication failed. Please check SMTP credentials.")

    except smtplib.SMTPException as e:
        print(f"[EMAIL SERVICE] SMTP error: {e}")
        raise Exception(f"Failed to send email: {str(e)}")

    except Exception as e:
        print(f"[EMAIL SERVICE] Unexpected error: {e}")
        raise Exception(f"Failed to send email: {str(e)}")


async def send_email_with_template(
    to_email: str,
    template_name: str,
    template_data: Dict[str, Any],
    subject: str,
    from_email: Optional[str] = None,
    from_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send email using a template (placeholder for future template engine integration)

    Args:
        to_email: Recipient email
        template_name: Name of the email template
        template_data: Data to populate template
        subject: Email subject
        from_email: Sender email
        from_name: Sender name

    Returns:
        Dict with send status
    """
    # This is a placeholder for future template engine (Jinja2, etc.)
    # For now, just send the template_data as a simple HTML email

    html_content = f"""
    <html>
        <body>
            <h2>{subject}</h2>
            <p>Template: {template_name}</p>
            <pre>{template_data}</pre>
        </body>
    </html>
    """

    return await send_email_smtp(
        to_email=to_email,
        subject=subject,
        html_content=html_content,
        from_email=from_email,
        from_name=from_name
    )
