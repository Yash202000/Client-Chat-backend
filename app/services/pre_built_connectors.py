
PRE_BUILT_CONNECTORS = {
    "crm": {
        "name": "CRM Connector",
        "description": "Connects to a CRM to manage customer data.",
        "parameters": {
            "api_key": {"type": "string", "description": "API key for the CRM"},
            "domain": {"type": "string", "description": "Domain of the CRM instance"}
        }
    },
    "email": {
        "name": "Email Connector",
        "description": "Connects to an email service to send and receive emails.",
        "parameters": {
            "smtp_server": {"type": "string", "description": "SMTP server address"},
            "port": {"type": "integer", "description": "Port number for the SMTP server"},
            "username": {"type": "string", "description": "Username for the email account"},
            "password": {"type": "string", "description": "Password for the email account"}
        }
    },
    "calendar": {
        "name": "Calendar Connector",
        "description": "Connects to a calendar service to manage events.",
        "parameters": {
            "api_key": {"type": "string", "description": "API key for the calendar service"},
            "calendar_id": {"type": "string", "description": "ID of the calendar to manage"}
        }
    },
    "payment_gateway": {
        "name": "Payment Gateway Connector",
        "description": "Connects to a payment gateway to process payments.",
        "parameters": {
            "api_key": {"type": "string", "description": "API key for the payment gateway"},
            "merchant_id": {"type": "string", "description": "ID of the merchant account"}
        }
    }
}
