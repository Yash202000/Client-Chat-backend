import google.generativeai as genai
from sqlalchemy.orm import Session
from app.services import credential_service
from app.services.vault_service import vault_service
from app.core.config import settings
from PIL import Image
import io
import os
import uuid
import json
from typing import AsyncGenerator, Union, Dict, List

genai.configure(api_key=settings.GOOGLE_API_KEY)

async def generate_response(
    db: Session,
    company_id: int,
    model_name: str,
    system_prompt: str,
    chat_history: list,
    tools: list = None,
    api_key: str = None,
    tool_choice: str = "auto",
    stream: bool = None
) -> Union[Dict, AsyncGenerator[str, None]]:
    # Use settings default if stream parameter is not explicitly set
    if stream is None:
        stream = settings.LLM_STREAMING_ENABLED

    if api_key is None:
        credential = credential_service.get_credential_by_service_name(db, service_name="gemini", company_id=company_id)
        if not credential:
            raise ValueError("Gemini API key not found for this company.")
        api_key = vault_service.decrypt(credential.encrypted_credentials)

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

    # STREAMING MODE: Cannot use tools with streaming currently
    if stream and not tools:
        async def stream_response():
            full_content = ""
            try:
                response = await model_chat_session.send_message_async(user_prompt, stream=True)

                async for chunk in response:
                    if chunk.text:
                        token = chunk.text
                        full_content += token
                        yield json.dumps({"type": "stream", "content": token})

                # Send final message indicating completion
                yield json.dumps({"type": "stream_end", "full_content": full_content})

            except Exception as e:
                print(f"Gemini Streaming Error: {e}")
                yield json.dumps({"type": "error", "content": f"LLM provider error: {e}"})

        return stream_response()

    # NON-STREAMING MODE: Original logic with tool support
    response = await model_chat_session.send_message_async(user_prompt)

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
