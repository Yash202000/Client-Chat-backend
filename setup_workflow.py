
import requests
import json

BASE_URL = "http://localhost:8000/api/v1"
COMPANY_ID = 1
AGENT_ID = 1

def create_add_numbers_workflow():
    payload = {
        "name": "Add Numbers Workflow",
        "description": "A workflow to add two numbers provided in the context.",
        "agent_id": AGENT_ID,
        "steps": {
            "steps": {
                "step1": {
                    "tool": "calculate_sum",
                    "params": {
                        "num1": "{{context.num1}}",
                        "num2": "{{context.num2}}"
                    },
                    "next_step_on_success": "final_response"
                },
                "final_response": {
                    "tool": "communication_tool",
                    "params": {
                        "message": "The sum is: {{step1.output}}"
                    }
                }
            }
        }
    }
    response = requests.post(
        f"{BASE_URL}/workflows/",
        headers={"Content-Type": "application/json", "X-Company-ID": str(COMPANY_ID)},
        data=json.dumps(payload)
    )
    if response.status_code == 200:
        print("Successfully created 'Add Numbers Workflow'.")
        return response.json()
    else:
        print(f"Failed to create 'Add Numbers Workflow'. Status: {response.status_code}, Response: {response.text}")
        return None

if __name__ == "__main__":
    create_add_numbers_workflow()
