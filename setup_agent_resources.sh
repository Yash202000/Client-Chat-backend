#!/bin/bash

# --- Configuration ---
BASE_URL="http://localhost:8000/api/v1"
COMPANY_ID="1"
AGENT_ID="1" # Assuming the default agent created by backend startup has ID 1

# --- Check for jq installation ---
if ! command -v jq &> /dev/null
then
    echo "Error: 'jq' is not installed. Please install it to run this script."
    echo "  On Debian/Ubuntu: sudo apt-get install jq"
    echo "  On macOS: brew install jq"
    exit 1
fi

# --- Get Groq API Key from .env ---
ENV_FILE="/home/developer/personal/AgentConnect/backend/.env"
if [ -f "$ENV_FILE" ]; then
  GROQ_API_KEY=$(grep -E '^GROQ_API_KEY=' "$ENV_FILE" | cut -d '=' -f2- | tr -d '"\')
else
  echo "Error: .env file not found at $ENV_FILE. Please create it with GROQ_API_KEY."
  exit 1
fi

if [ -z "$GROQ_API_KEY" ]; then
  echo "Error: GROQ_API_KEY not found or is empty in $ENV_FILE. Please set it."
  exit 1
fi


echo "--- Setting up AgentConnect Backend Resources ---"

# --- 1. Create Groq Credential ---
echo "1. Creating Groq Credential..."
CREDENTIAL_RESPONSE=$(curl -s -X POST "${BASE_URL}/credentials/" \
     -H "Content-Type: application/json" \
     -H "X-Company-ID: ${COMPANY_ID}" \
     -d "{
           \"name\": \"Groq API Key\",
           \"platform\": \"groq\",
           \"api_key\": \"${GROQ_API_KEY}\"
         }")

CREDENTIAL_ID=$(echo "$CREDENTIAL_RESPONSE" | jq -r '.id')

if [ "$CREDENTIAL_ID" == "null" ] || [ -z "$CREDENTIAL_ID" ]; then
  echo "Failed to create Groq Credential. Response: $CREDENTIAL_RESPONSE"
  exit 1
fi
echo "   Groq Credential created with ID: $CREDENTIAL_ID"

# --- 2. Assign Credential to Default Agent ---
echo "2. Assigning Groq Credential to Agent ID ${AGENT_ID}..."
AGENT_UPDATE_RESPONSE=$(curl -s -X PUT "${BASE_URL}/agents/${AGENT_ID}" \
     -H "Content-Type: application/json" \
     -H "X-Company-ID: ${COMPANY_ID}" \
     -d "{
           \"credential_id\": ${CREDENTIAL_ID}
         }")

if echo "$AGENT_UPDATE_RESPONSE" | grep -q "id"; then
  echo "   Agent ${AGENT_ID} updated with Credential ID ${CREDENTIAL_ID}."
else
  echo "   Failed to update Agent ${AGENT_ID}. Response: $AGENT_UPDATE_RESPONSE"
  exit 1
fi

# --- 3. Create 'add_numbers' Tool ---
echo "3. Creating 'add_numbers' Tool..."
ADD_NUMBERS_TOOL_RESPONSE=$(curl -s -X POST "${BASE_URL}/tools/" \
     -H "Content-Type: application/json" \
     -H "X-Company-ID: ${COMPANY_ID}" \
     -d '{
           "name": "add_numbers",
           "description": "Adds two numbers together.",
           "parameters": {
             "type": "object",
             "properties": {
               "a": {
                 "type": "number",
                 "description": "The first number"
               },
               "b": {
                 "type": "number",
                 "description": "The second number"
               }
             },
             "required": ["a", "b"]
           },
           "code": "a = args.get(\"a\")\nb = args.get(\"b\")\n\nif isinstance(a, (int, float)) and isinstance(b, (int, float)):\n    result = a + b\nelse:\n    result = \"Error: Both 'a' and 'b' must be numbers.\""
         }')

ADD_NUMBERS_TOOL_ID=$(echo "$ADD_NUMBERS_TOOL_RESPONSE" | jq -r '.id')

if [ "$ADD_NUMBERS_TOOL_ID" == "null" ] || [ -z "$ADD_NUMBERS_TOOL_ID" ]; then
  echo "Failed to create 'add_numbers' tool. Response: $ADD_NUMBERS_TOOL_RESPONSE"
  exit 1
fi
echo "   'add_numbers' Tool created with ID: $ADD_NUMBERS_TOOL_ID"

# --- 4. Create 'communication_tool' ---
echo "4. Creating 'communication_tool'..."
COMMUNICATION_TOOL_RESPONSE=$(curl -s -X POST "${BASE_URL}/tools/" \
     -H "Content-Type: application/json" \
     -H "X-Company-ID: ${COMPANY_ID}" \
     -d '{
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
           "code": "message = args.get(\"message\", \"\")\nexec_globals[\"result\"] = message"
         }')

COMMUNICATION_TOOL_ID=$(echo "$COMMUNICATION_TOOL_RESPONSE" | jq -r '.id')

if [ "$COMMUNICATION_TOOL_ID" == "null" ] || [ -z "$COMMUNICATION_TOOL_ID" ]; then
  echo "Failed to create 'communication_tool'. Response: $COMMUNICATION_TOOL_RESPONSE"
  exit 1
fi
echo "   'communication_tool' Tool created with ID: $COMMUNICATION_TOOL_ID"

# --- 5. Create 'trigger_workflow' Tool ---
echo "5. Creating 'trigger_workflow' Tool..."
TRIGGER_WORKFLOW_TOOL_RESPONSE=$(curl -s -X POST "${BASE_URL}/tools/" \
     -H "Content-Type: application/json" \
     -H "X-Company-ID: ${COMPANY_ID}" \
     -d '{
           "name": "trigger_workflow",
           "description": "Triggers a specific workflow with provided inputs.",
           "parameters": {
             "type": "object",
             "properties": {
               "workflow_name": {
                 "type": "string",
                 "description": "The name of the workflow to trigger."
               },
               "inputs": {
                 "type": "object",
                 "description": "A JSON object containing key-value pairs of inputs for the workflow."
               }
             },
             "required": ["workflow_name", "inputs"]
           },
           "code": "workflow_name = args.get(\"workflow_name\")\ninputs = args.get(\"inputs\", {}\nresult = {\"workflow_name\": workflow_name, \"inputs\": inputs}"
         }')

TRIGGER_WORKFLOW_TOOL_ID=$(echo "$TRIGGER_WORKFLOW_TOOL_RESPONSE" | jq -r '.id')

if [ "$TRIGGER_WORKFLOW_TOOL_ID" == "null" ] || [ -z "$TRIGGER_WORKFLOW_TOOL_ID" ]; then
  echo "Failed to create 'trigger_workflow' tool. Response: $TRIGGER_WORKFLOW_TOOL_RESPONSE"
  exit 1
fi
echo "   'trigger_workflow' Tool created with ID: $TRIGGER_WORKFLOW_TOOL_ID"

# --- 6. Create 'Add Numbers Workflow' ---
echo "6. Creating 'Add Numbers Workflow'..."
WORKFLOW_RESPONSE=$(curl -s -X POST "${BASE_URL}/workflows/" \
     -H "Content-Type: application/json" \
     -H "X-Company-ID: ${COMPANY_ID}" \
     -d "{
           "name": "Add Numbers Workflow",
           "description": "A workflow to add two numbers provided in the context.",
           "agent_id": ${AGENT_ID},
           "steps": {
             "step1": {
               "tool": "add_numbers",
               "params": {
                 "a": "{{context.num1}}",
                 "b": "{{context.num2}}"
               },
               "next_step_on_success": "final_response"
             },
             "final_response": {
               "tool": "communication_tool",
               "params": {
                 "message": "The sum is: {{step1.output}}",
                 "recipient": "user"
               }
             }
           }
         }")

WORKFLOW_ID=$(echo "$WORKFLOW_RESPONSE" | jq -r '.id')

if [ "$WORKFLOW_ID" == "null" ] || [ -z "$WORKFLOW_ID" ]; then
  echo "Failed to create 'Add Numbers Workflow'. Response: $WORKFLOW_RESPONSE"
  exit 1
fi
echo "   'Add Numbers Workflow' created with ID: $WORKFLOW_ID"

echo "--- Setup Complete ---"
echo "You can now interact with Agent ID ${AGENT_ID} to test the workflow."
echo "Remember to restart your backend server if you made any code changes."
