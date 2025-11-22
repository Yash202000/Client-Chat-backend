import google.generativeai as genai
from sqlalchemy.orm import Session
from app.services import credential_service
from app.services.vault_service import vault_service
from app.core.config import settings
import requests
from PIL import Image
import io
import os
import uuid



genai.configure(api_key=settings.GOOGLE_API_KEY)

def generate_response(db: Session, company_id: int, model_name: str, system_prompt: str, chat_history: list, tools: list, api_key: str = None, tool_choice: str = "auto"):
    if api_key is None:
        credential = credential_service.get_credential_by_service_name(db, service_name="gemini", company_id=company_id)
        if not credential:
            raise ValueError("Gemini API key not found for this company.")
        api_key =   vault_service.decrypt(credential.encrypted_credentials)

    if not api_key:
        raise ValueError("GOOGLE_API_KEY is not configured for this agent.")
    
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system_prompt,
        tools=tools if tools else None
    )

    gemini_history = []
    for msg in chat_history:
        role = 'user' if msg.sender == 'user' else 'model'
        gemini_history.append({"role": role, "parts": [{"text": msg.message}]})

    user_prompt = gemini_history.pop(-1)['parts'][0]['text']

    model_chat_session = model.start_chat(history=gemini_history)
    response = model_chat_session.send_message(user_prompt)

    try:
        function_call = response.candidates[0].content.parts[0].function_call
        if function_call:
            return {
                "type": "tool_call",
                "tool_name": function_call.name,
                "parameters": {key: value for key, value in function_call.args.items()}
            }
    except (ValueError, AttributeError, IndexError):
        pass

    return {"type": "text", "content": response.text}

def generate_image(prompt: str):
    

    model = genai.GenerativeModel('gemini-2.5-flash-image-preview')
    response = model.generate_content(prompt)

    
    for part in response.candidates[0].content.parts:
        if part.text is not None:
            print(part.text)
        elif part.inline_data is not None:
            image = Image.open(io.BytesIO(part.inline_data.data))
            # Ensure the directory exists
            save_dir = "/home/developer/personal/AgentConnect/backend/app/generated_images"
            os.makedirs(save_dir, exist_ok=True)
            
            # Generate a unique filename
            filename = f"{uuid.uuid4()}.png"
            filepath = os.path.join(save_dir, filename)
            
            image.save(filepath)
            
            # Return the path to the saved image
            
            return image
