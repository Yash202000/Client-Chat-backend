"""
Automax Proxy API endpoint.
Proxies image upload to Automax API to bypass browser CSP restrictions.
"""
from fastapi import APIRouter, HTTPException, UploadFile, File
import requests
import os

router = APIRouter()

# Automax configuration from environment
AUTOMAX_BASEURL = os.getenv("AUTOMAX_BASEURL", "https://automax.discretal.com")
AUTOMAX_USERNAME = os.getenv("AUTOMAX_USERNAME", "430410420708900865")
AUTOMAX_PASSWORD = os.getenv("AUTOMAX_PASSWORD", "eCOALLWlcunoKl3Y2yHEfSS7h1swZvrXBCOPnPGS0WboqSkzZ1BaR9R3x2dPkBV0")
AUTOMAX_NAMESPACE = os.getenv("AUTOMAX_NAMESPACE", "431842611944685569")
AUTOMAX_MODULE = os.getenv("AUTOMAX_MODULE", "431842611943440385")


def get_automax_token() -> str | None:
    """Get OAuth token from Automax API."""
    url = f"{AUTOMAX_BASEURL}/auth/oauth2/token"
    
    try:
        response = requests.post(
            url,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(AUTOMAX_USERNAME, AUTOMAX_PASSWORD),
            data={
                "grant_type": "client_credentials",
                "scope": "profile api"
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("access_token")
        else:
            print(f"[Automax Proxy] Token request failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"[Automax Proxy] Token error: {e}")
        return None


@router.post("/upload-attachment")
async def upload_attachment(file: UploadFile = File(...)):
    """
    Proxy endpoint to upload image to Automax and return attachment_id.
    
    Frontend calls this instead of Automax directly (bypasses CSP).
    """
    try:
        # Get auth token
        token = get_automax_token()
        if not token:
            raise HTTPException(status_code=500, detail="Failed to authenticate with Automax")
        
        # Read file content
        file_content = await file.read()
        
        # Upload to Automax
        url = f"{AUTOMAX_BASEURL}/api/compose/namespace/{AUTOMAX_NAMESPACE}/module/{AUTOMAX_MODULE}/record/attachment"
        
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            data={"fieldName": "Attachments"},
            files={"upload": (file.filename or "image.jpg", file_content, file.content_type or "image/jpeg")}
        )
        
        print(f"[Automax Proxy] Upload response: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            attachment_id = data.get("response", {}).get("attachmentID", "")
            
            if attachment_id:
                print(f"[Automax Proxy] Attachment ID: {attachment_id}")
                return {
                    "success": True,
                    "attachment_id": attachment_id
                }
            else:
                print(f"[Automax Proxy] No attachment ID in response: {data}")
                return {
                    "success": True,
                    "attachment_id": "",
                    "warning": "No attachment ID returned",
                    "raw_response": data
                }
        else:
            print(f"[Automax Proxy] Upload failed: {response.text}")
            raise HTTPException(status_code=response.status_code, detail=f"Automax upload failed: {response.text}")
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"[Automax Proxy] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
