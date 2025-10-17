import httpx
from fastapi import APIRouter, Request, Response
from starlette.responses import StreamingResponse
from app.core.config import settings

router = APIRouter()

@router.get("/image-proxy")
async def image_proxy(url: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            
            # Stream the response back to the client
            return StreamingResponse(response.iter_bytes(), media_type=response.headers.get("content-type"))
        except httpx.RequestError as e:
            return Response(status_code=400, content=f"Could not fetch image: {e}")
        except httpx.HTTPStatusError as e:
            return Response(status_code=e.response.status_code, content=e.response.content)

@router.post("/linkedin/oauth/v2/accessToken")
async def linkedin_access_token_proxy(request: Request):
    async with httpx.AsyncClient() as client:
        try:
            data = await request.json()
            code = data.get("code")
            redirect_uri = data.get("redirect_uri")

            payload = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": settings.LINKEDIN_CLIENT_ID,
                "client_secret": settings.LINKEDIN_CLIENT_SECRET,
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }

            response = await client.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data=payload,
                headers=headers
            )
            
            response.raise_for_status()
            return Response(content=response.content, status_code=response.status_code, media_type=response.headers.get("content-type"))

        except httpx.RequestError as e:
            return Response(status_code=400, content=f"Could not fetch token: {e}")
        except httpx.HTTPStatusError as e:
            return Response(status_code=e.response.status_code, content=e.response.content)