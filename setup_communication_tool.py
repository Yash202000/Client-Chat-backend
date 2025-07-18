import requests
import json

BASE_URL = "http://localhost:8000/api/v1"
COMPANY_ID = 1

def create_communication_tool():
    payload = {
        "name": "communication_tool",
        "description": "Communicates a message to a recipient.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to communicate"
                },
                "recipient": {
                    "type": "string",
                    "description": "The recipient of the message (e.g., user, admin)",
                    "default": "user"
                }
            },
            "required": ["message"]
        },
        "code": "def run(params, config):\n    message = params.get(\"message\")\n    recipient = params.get(\"recipient\")\n    # In a real scenario, you would send the message to the recipient here.\n    # For now, we just return the message.\n    return f\"Message to {recipient}: {message}\""
    }
    response = requests.post(
        f"{BASE_URL}/tools/",
        headers={"Content-Type": "application/json", "X-Company-ID": str(COMPANY_ID)},
        data=json.dumps(payload)
    )
    if response.status_code == 200:
        print("Successfully created 'communication_tool'.")
        return response.json()
    else:
        print(f"Failed to create 'communication_tool'. Status: {response.status_code}, Response: {response.text}")
        return None

if __name__ == "__main__":
    create_communication_tool()
