"""License-related exceptions and error handling."""

from fastapi import Request, status
from fastapi.responses import HTMLResponse, JSONResponse
import os


class LicenseError(Exception):
    """Base exception for license errors."""
    def __init__(self, message: str, status_type: str = "invalid"):
        self.message = message
        self.status_type = status_type  # "expired", "invalid", "not_configured"
        super().__init__(self.message)


class LicenseExpiredError(LicenseError):
    """Raised when license has expired."""
    def __init__(self, message: str = "License expired. Please contact your administrator to renew the license."):
        super().__init__(message, "expired")


class LicenseInvalidError(LicenseError):
    """Raised when license is invalid."""
    def __init__(self, message: str = "License is invalid. Please contact your administrator."):
        super().__init__(message, "invalid")


class LicenseNotConfiguredError(LicenseError):
    """Raised when no license is configured."""
    def __init__(self, message: str = "No license configured. Please contact your administrator."):
        super().__init__(message, "not_configured")


def get_license_error_html(status_type: str, message: str) -> str:
    """Generate the license error HTML page."""
    template_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "templates",
        "license_error.html"
    )

    # Status configurations
    status_configs = {
        "expired": {
            "class": "expired",
            "text": "License Expired"
        },
        "invalid": {
            "class": "invalid",
            "text": "Invalid License"
        },
        "not_configured": {
            "class": "not-configured",
            "text": "Not Configured"
        }
    }

    config = status_configs.get(status_type, status_configs["invalid"])

    try:
        with open(template_path, "r") as f:
            html = f.read()

        # Replace placeholders
        html = html.replace("{{status_class}}", config["class"])
        html = html.replace("{{status_text}}", config["text"])
        html = html.replace("{{message}}", message)

        return html
    except FileNotFoundError:
        # Fallback simple HTML if template not found
        return f"""
        <!DOCTYPE html>
        <html>
        <head><title>License Error</title></head>
        <body style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>License Error</h1>
            <p>{message}</p>
            <p>Contact: Yash Panchwatkar - yashpanchwatkar@gmail.com - +91 7083581881</p>
        </body>
        </html>
        """


async def license_exception_handler(request: Request, exc: LicenseError):
    """
    Handle license exceptions.
    Returns HTML for browser requests, JSON for API requests.
    """
    # Check if request is from browser (accepts HTML)
    accept_header = request.headers.get("accept", "")
    is_browser = "text/html" in accept_header and "application/json" not in accept_header

    if is_browser:
        html_content = get_license_error_html(exc.status_type, exc.message)
        return HTMLResponse(
            content=html_content,
            status_code=status.HTTP_403_FORBIDDEN
        )
    else:
        # Return JSON for API clients
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": exc.message,
                "error_type": "license_error",
                "license_status": exc.status_type,
                "contact": {
                    "name": "Yash Panchwatkar",
                    "email": "yashpanchwatkar@gmail.com",
                    "phone": "+91 7083581881"
                }
            }
        )
