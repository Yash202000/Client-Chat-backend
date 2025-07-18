
import requests
import json

BASE_URL = "http://localhost:8000/api/v1"
COMPANY_ID = 1

def get_tool_code(filename):
    with open(filename, 'r') as f:
        return f.read()

def create_calculate_sum_tool():
    tool_code = get_tool_code('calculate_sum_tool_code.py')
    payload = {
        "name": "calculate_sum",
        "description": "Calculates the sum of two numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "num1": {"type": "number", "description": "The first number"},
                "num2": {"type": "number", "description": "The second number"}
            },
            "required": ["num1", "num2"]
        },
        "code": tool_code
    }
    response = requests.post(
        f"{BASE_URL}/tools/",
        headers={"Content-Type": "application/json", "X-Company-ID": str(COMPANY_ID)},
        data=json.dumps(payload)
    )
    if response.status_code == 200:
        print("Successfully created 'calculate_sum' tool.")
        return response.json()
    else:
        print(f"Failed to create 'calculate_sum' tool. Status: {response.status_code}, Response: {response.text}")
        return None

if __name__ == "__main__":
    create_calculate_sum_tool()
