
import httpx
from fastapi import APIRouter, Request, Response
from starlette.responses import StreamingResponse

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
