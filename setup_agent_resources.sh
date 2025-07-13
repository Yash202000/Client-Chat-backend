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

# --- 0. Delete the old 'trigger_workflow' tool if it exists ---
echo "0. Deleting 'trigger_workflow' tool to ensure a clean slate..."
# First, get all tools to find the ID
ALL_TOOLS=$(curl -s -X GET "${BASE_URL}/tools/?company_id=${COMPANY_ID}" -H "X-Company-ID: ${COMPANY_ID}")
TRIGGER_WORKFLOW_TOOL_ID=$(echo "$ALL_TOOLS" | jq -r '.[] | select(.name == "trigger_workflow") | .id')

if [ -n "$TRIGGER_WORKFLOW_TOOL_ID" ] && [ "$TRIGGER_WORKFLOW_TOOL_ID" != "null" ]; then
  echo "   Found 'trigger_workflow' tool with ID: ${TRIGGER_WORKFLOW_TOOL_ID}. Deleting it..."
  DELETE_RESPONSE=$(curl -s -X DELETE "${BASE_URL}/tools/${TRIGGER_WORKFLOW_TOOL_ID}" -H "X-Company-ID: ${COMPANY_ID}")
  echo "   Deletion response: $DELETE_RESPONSE"
else
  echo "   'trigger_workflow' tool not found. Skipping deletion."
fi


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

# --- 3. Create 'calculate_sum' Tool ---
echo "3. Creating 'calculate_sum' Tool..."
# Read the tool code from its dedicated file
CALCULATE_SUM_TOOL_CODE=$(cat calculate_sum_tool_code.py)

# Use jq to safely build the JSON payload on a single line to avoid shell parsing issues
JSON_PAYLOAD=$(jq -n --arg name "calculate_sum" --arg description "Calculates the sum of two numbers." --argjson params '{"type": "object", "properties": {"num1": {"type": "number", "description": "The first number"}, "num2": {"type": "number", "description": "The second number"}}, "required": ["num1", "num2"]}' --arg code "$CALCULATE_SUM_TOOL_CODE" '{name: $name, description: $description, parameters: $params, code: $code}')

CALCULATE_SUM_TOOL_RESPONSE=$(curl -s -X POST "${BASE_URL}/tools/" \
     -H "Content-Type: application/json" \
     -H "X-Company-ID: ${COMPANY_ID}" \
     -d "$JSON_PAYLOAD")

CALCULATE_SUM_TOOL_ID=$(echo "$CALCULATE_SUM_TOOL_RESPONSE" | jq -r '.id')


if [ "$CALCULATE_SUM_TOOL_ID" == "null" ] || [ -z "$CALCULATE_SUM_TOOL_ID" ]; then
  echo "Failed to create 'calculate_sum' tool. Response: $CALCULATE_SUM_TOOL_RESPONSE"
  exit 1
fi
echo "   'calculate_sum' Tool created with ID: $CALCULATE_SUM_TOOL_ID"


# --- 4. Associate tool with agent ---
echo "4. Associating tool with agent..."
# First, get the agent's current data to get the list of tool_ids
AGENT_DATA=$(curl -s -X GET "${BASE_URL}/agents/${AGENT_ID}" -H "X-Company-ID: ${COMPANY_ID}")
CURRENT_TOOL_IDS=$(echo "$AGENT_DATA" | jq '.tool_ids // []')

# Add the new tool ID to the list, ensuring no duplicates
UPDATED_TOOL_IDS=$(echo "$CURRENT_TOOL_IDS" | jq ". + [${CALCULATE_SUM_TOOL_ID}] | unique")

# Create the JSON payload for the update
AGENT_UPDATE_PAYLOAD=$(jq -n --argjson ids "$UPDATED_TOOL_IDS" '{"tool_ids": $ids}')

# Send the PUT request to update the agent
ASSOCIATE_TOOL_RESPONSE=$(curl -s -X PUT "${BASE_URL}/agents/${AGENT_ID}" \
     -H "Content-Type: application/json" \
     -H "X-Company-ID: ${COMPANY_ID}" \
     -d "$AGENT_UPDATE_PAYLOAD")

# Check if the response contains the agent's ID, indicating success
if echo "$ASSOCIATE_TOOL_RESPONSE" | jq -e '.id' > /dev/null; then
    echo "   Tool ${CALCULATE_SUM_TOOL_ID} successfully associated with Agent ${AGENT_ID}."
else
    echo "   Failed to associate tool. Response: $ASSOCIATE_TOOL_RESPONSE"
    exit 1
fi




# # --- 4. Create 'communication_tool' ---
# echo "4. Creating 'communication_tool'..."
# COMMUNICATION_TOOL_RESPONSE=$(curl -s -X POST "${BASE_URL}/tools/" \
#      -H "Content-Type: application/json" \
#      -H "X-Company-ID: ${COMPANY_ID}" \
#      -d '{
#            "name": "communication_tool",
#            "description": "Communicates a message to a recipient.",
#            "parameters": {
#              "type": "object",
#              "properties": {
#                "message": {
#                  "type": "string",
#                  "description": "The message to communicate"
#                },
#                "recipient": {
#                  "type": "string",
#                  "description": "The recipient of the message (e.g., user, admin)",
#                  "default": "user"
#                }
#              },
#              "required": ["message"]
#            },
#            "code": "message = args.get(\"message\", \"\")\nexec_globals[\"result\"] = message"
#          }')

# COMMUNICATION_TOOL_ID=$(echo "$COMMUNICATION_TOOL_RESPONSE" | jq -r '.id')

# if [ "$COMMUNICATION_TOOL_ID" == "null" ] || [ -z "$COMMUNICATION_TOOL_ID" ]; then
#   echo "Failed to create 'communication_tool'. Response: $COMMUNICATION_TOOL_RESPONSE"
#   exit 1
# fi
# echo "   'communication_tool' Tool created with ID: $COMMUNICATION_TOOL_ID"

# TRIGGER_WORKFLOW_TOOL_CODE=$(cat trigger_workflow_tool_code.py | jq -Rs .)

# # --- 5. Create 'trigger_workflow' Tool ---
# echo "5. Creating 'trigger_workflow' Tool..."
# TRIGGER_WORKFLOW_TOOL_RESPONSE=$(curl -s -X POST "${BASE_URL}/tools/" \
#      -H "Content-Type: application/json" \
#      -H "X-Company-ID: ${COMPANY_ID}" \
#      -d "{
#            \"name\": \"trigger_workflow\",
#            \"description\": \"Initiates a predefined workflow by its name and passes a dictionary of inputs to it. Use this tool when a user's request clearly maps to a known automated process.\",
#            \"parameters\": {
#              \"type\": \"object\",
#              \"properties\": {
#                \"workflow_name\": {
#                  \"type\": \"string\",
#                  \"description\": \"The name of the workflow to trigger.\"
#                },
#                \"inputs\": {
#                  \"type\": \"object\",
#                  \"description\": \"A JSON object containing key-value pairs of inputs for the workflow.\"
#                }
#              },
#              \"required\": [\"workflow_name\", \"inputs\"]
#            },
#            \"code\": ${TRIGGER_WORKFLOW_TOOL_CODE}
#          }")

# TRIGGER_WORKFLOW_TOOL_ID=$(echo "$TRIGGER_WORKFLOW_TOOL_RESPONSE" | jq -r '.id')

# if [ "$TRIGGER_WORKFLOW_TOOL_ID" == "null" ] || [ -z "$TRIGGER_WORKFLOW_TOOL_ID" ]; then
#   echo "Failed to create 'trigger_workflow' tool. Response: $TRIGGER_WORKFLOW_TOOL_RESPONSE"
#   exit 1
# fi
# echo "   'trigger_workflow' Tool created with ID: $TRIGGER_WORKFLOW_TOOL_ID"

# # --- 6. Create 'Add Numbers Workflow' ---
# echo "6. Creating 'Add Numbers Workflow'..."
# WORKFLOW_RESPONSE=$(curl -s -X POST "${BASE_URL}/workflows/" \
#      -H "Content-Type: application/json" \
#      -H "X-Company-ID: ${COMPANY_ID}" \
#      -d "{\"name\": \"Add Numbers Workflow\",\"description\": \"A workflow to add two numbers provided in the context.\",\"agent_id\": ${AGENT_ID},\"steps\": {\"step1\": {\"tool\": \"add_numbers\",\"params\": {\"a\": \"{{context.num1}}\",\"b\": \"{{context.num2}}\"},\"next_step_on_success\": \"final_response\"},\"final_response\": {\"tool\": \"communication_tool\",\"params\": {\"message\": \"The sum is: {{step1.output}}\",\"recipient\": \"user\"}}}}")


