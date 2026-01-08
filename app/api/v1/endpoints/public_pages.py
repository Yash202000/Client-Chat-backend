"""
Public pages endpoint for legal pages (Privacy Policy, Terms of Service)
These are required by Meta/Facebook for app verification
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

PRIVACY_POLICY_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Privacy Policy - AgentConnect</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
            color: #333;
            background: #f9fafb;
        }
        h1 { color: #111; border-bottom: 2px solid #3b82f6; padding-bottom: 10px; }
        h2 { color: #1f2937; margin-top: 30px; }
        ul { padding-left: 25px; }
        li { margin: 8px 0; }
        .container { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .updated { color: #6b7280; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Privacy Policy</h1>
        <p class="updated">Last updated: January 2026</p>

        <h2>1. Information We Collect</h2>
        <p>AgentConnect collects information necessary to provide our conversational AI services, including:</p>
        <ul>
            <li>Messages sent through connected platforms (Instagram, WhatsApp, Messenger, etc.)</li>
            <li>Contact information provided through messaging platforms</li>
            <li>Usage data and interaction logs</li>
        </ul>

        <h2>2. How We Use Your Information</h2>
        <p>We use collected information to:</p>
        <ul>
            <li>Provide automated responses and customer support</li>
            <li>Improve our AI and workflow systems</li>
            <li>Analyze usage patterns to enhance our services</li>
        </ul>

        <h2>3. Data Storage and Security</h2>
        <p>We implement appropriate security measures to protect your data. All credentials and sensitive information are encrypted at rest and in transit.</p>

        <h2>4. Third-Party Services</h2>
        <p>AgentConnect integrates with third-party platforms including Meta (Instagram, Facebook Messenger), WhatsApp, Telegram, and others. Your use of these platforms is subject to their respective privacy policies.</p>

        <h2>5. Data Deletion</h2>
        <p>You may request deletion of your data by contacting us. We will process deletion requests in accordance with applicable laws.</p>

        <h2>6. Contact Us</h2>
        <p>For questions about this privacy policy, please contact us through the AgentConnect platform.</p>
    </div>
</body>
</html>
"""

@router.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy():
    """Return the privacy policy page"""
    return PRIVACY_POLICY_HTML

@router.get("/terms-of-service", response_class=HTMLResponse)
async def terms_of_service():
    """Return the terms of service page"""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Terms of Service - AgentConnect</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 40px 20px;
            color: #333;
            background: #f9fafb;
        }
        h1 { color: #111; border-bottom: 2px solid #3b82f6; padding-bottom: 10px; }
        h2 { color: #1f2937; margin-top: 30px; }
        .container { background: white; padding: 40px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .updated { color: #6b7280; font-size: 14px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Terms of Service</h1>
        <p class="updated">Last updated: January 2026</p>

        <h2>1. Acceptance of Terms</h2>
        <p>By using AgentConnect, you agree to these terms of service.</p>

        <h2>2. Use of Service</h2>
        <p>AgentConnect provides AI-powered conversational tools for businesses. You agree to use the service in accordance with all applicable laws.</p>

        <h2>3. User Responsibilities</h2>
        <p>You are responsible for maintaining the security of your account and for all activities under your account.</p>

        <h2>4. Limitation of Liability</h2>
        <p>AgentConnect is provided "as is" without warranties of any kind.</p>

        <h2>5. Contact</h2>
        <p>For questions about these terms, please contact us through the AgentConnect platform.</p>
    </div>
</body>
</html>
"""
