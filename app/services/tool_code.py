
TOOL_CODE = {
    "crm": '''
import requests

def run(params, config):
    api_key = config.get("api_key")
    domain = config.get("domain")
    # Add your CRM API logic here
    return f"Connecting to {domain} with API key {api_key}"
''',
    "email": '''
import smtplib

def run(params, config):
    smtp_server = config.get("smtp_server")
    port = config.get("port")
    username = config.get("username")
    password = config.get("password")
    # Add your email sending logic here
    return f"Connecting to {smtp_server} on port {port} with username {username}"
''',
    "calendar": '''
import requests

def run(params, config):
    api_key = config.get("api_key")
    calendar_id = config.get("calendar_id")
    # Add your calendar API logic here
    return f"Connecting to calendar {calendar_id} with API key {api_key}"
''',
    "payment_gateway": '''
import requests

def run(params, config):
    api_key = config.get("api_key")
    merchant_id = config.get("merchant_id")
    # Add your payment gateway logic here
    return f"Connecting to payment gateway with merchant ID {merchant_id} and API key {api_key}"
'''
}
