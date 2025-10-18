import httpx
import base64
from fastapi import APIRouter, Request, Response
from starlette.responses import StreamingResponse
from app.core.config import settings

router = APIRouter()

# 1x1 transparent PNG as base64 fallback
FALLBACK_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

@router.get("/image-proxy")
async def image_proxy(url: str):
    """
    Proxy images from external URLs to avoid CORS issues.
    Returns a transparent 1x1 PNG fallback if the image cannot be fetched.
    """
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        try:
            response = await client.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            response.raise_for_status()

            # Stream the response back to the client
            return StreamingResponse(
                response.iter_bytes(),
                media_type=response.headers.get("content-type", "image/png")
            )
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            # Return a transparent 1x1 PNG fallback instead of an error
            print(f"[image-proxy] Failed to fetch image from {url}: {e}")
            return Response(
                content=FALLBACK_IMAGE,
                media_type="image/png",
                status_code=200  # Return 200 with fallback instead of error
            )

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