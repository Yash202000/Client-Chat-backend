import os
import json
import base64
import requests
from datetime import datetime
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
 
load_dotenv()

 
class Automax3:
    def __init__(self):
        self.base_url = os.getenv("AUTOMAX_BASEURL")
        self.userid = os.getenv("AUTOMAX_USERNAME")
        self.password = os.getenv("AUTOMAX_PASSWORD")
        self.namespaceid = os.getenv("AUTOMAX_NAMESPACE")
        self.moduleid = os.getenv("AUTOMAX_MODULE")
 
        if not self.base_url:
            raise RuntimeError("ENV not loaded. Check .env file path.")
 
        self.token = None
 
    # login once at startup
    def login(self):
        url = f"{self.base_url}/auth/oauth2/token"
 
        data = {
            "grant_type": "client_credentials",
            "scope": "profile api",
        }
 
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
 
        auth = HTTPBasicAuth(self.userid, self.password)
 
        r = requests.post(url, data=data, headers=headers, auth=auth)
 
        if r.status_code != 200:
            raise RuntimeError(f"Startup login failed: {r.text}")
 
        response = r.json()
        self.token = response["access_token"]
 
        print("✅ Automax login successful")
 
    def _headers(self):
        if not self.token:
            raise RuntimeError("Automax client used before login")
 
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
 
    # -----------------------------
    # READ APIs
    # -----------------------------
 
    def get_classifications(self):
        r = requests.get(
            f"{self.base_url}/api/classifications/hierarchy",
            headers=self._headers(),
        )
        r.raise_for_status()
 
        data = r.json()
        print("📂 Classifications:\n", json.dumps(data, indent=2))
 
        return data
 
    def get_locations(self):
        r = requests.get(
            f"{self.base_url}/api/locations/hierarchy",
            headers=self._headers(),
        )
        r.raise_for_status()
 
        data = r.json()
        print("📍 Locations:\n", json.dumps(data, indent=2))
 
        return data

    # -----------------------------
    # ATTACHMENT UPLOAD
    # -----------------------------

    def create_attachment(self, image_data):
        """
        Upload an image attachment and return the attachment ID.
        
        Args:
            image_data: Either raw bytes or a base64 encoded string
        """
        url = f"{self.base_url}/api/compose/namespace/{self.namespaceid}/module/{self.moduleid}/record/attachment"
        
        # Handle both raw bytes and base64 string
        if isinstance(image_data, bytes):
            # Already raw bytes
            img_bytes = image_data
        else:
            # Assume it's a base64 string
            image_base64 = image_data
            # Remove data URL prefix if present (e.g., "data:image/jpeg;base64,")
            if "," in image_base64:
                image_base64 = image_base64.split(",", 1)[1]
            
            # Fix base64 padding if needed
            padding = 4 - len(image_base64) % 4
            if padding != 4:
                image_base64 += "=" * padding
            
            # Decode base64 to bytes
            img_bytes = base64.b64decode(image_base64)
        
        print(f"📷 Image size: {len(img_bytes)} bytes")
        
        headers = {"Authorization": f"Bearer {self.token}"}
        body = {"fieldName": "Attachments"}
        files = {"upload": ("image.jpg", img_bytes, "image/jpeg")}
        
        r = requests.post(url, headers=headers, data=body, files=files)
        
        print(f"📤 Attachment upload response: status={r.status_code}, content-type={r.headers.get('content-type', 'unknown')}")
        print(f"📤 Response text (first 500 chars): {r.text[:500] if r.text else 'EMPTY'}")
        
        r.raise_for_status()
        
        # Handle empty or non-JSON responses
        if not r.text or not r.text.strip():
            print("⚠️ Empty response from attachment upload - returning placeholder ID")
            return "attachment_uploaded_no_id"
        
        try:
            data = r.json()
            attachment_id = data.get("response", {}).get("attachmentID", "")
            if not attachment_id:
                # Try alternative paths in response
                attachment_id = data.get("attachmentID", "") or data.get("id", "") or str(data)
            print(f"📎 Attachment uploaded: {attachment_id}")
            return attachment_id
        except Exception as e:
            print(f"⚠️ Could not parse attachment response as JSON: {e}")
            print(f"⚠️ Raw response: {r.text[:200]}")
            return "attachment_uploaded_parse_error"


    # -----------------------------
    # INCIDENT CREATION
    # -----------------------------

    def create_incident(
        self,
        caller_name: str,
        classification: str,
        location: str,
        attachment_id: str = "",
        coordinates: str = "",
        channel: str = "Chatbot",
        national_id: str = "45",
        criticality: str = "LOW",
    ):
        url = f"{self.base_url}/api/compose/namespace/{self.namespaceid}/module/{self.moduleid}/record/"
 
        body = {
            "meta": {},
            "records": [],
            "values": [
                {"name": "Channel", "value": channel},
                {"name": "Criticality", "value": criticality},
                {"name": "Caller_name", "value": caller_name},
                {"name": "Last_call_date", "value": datetime.utcnow().isoformat() + "Z"},
                {"name": "National_ID", "value": national_id},
                {"name": "Mobile_number", "value": ""},
                {"name": "Classification", "value": classification},
                {"name": "Incident_reason", "value": ""},
                {"name": "Incident_Description", "value": "incident created via MCP"},
                {"name": "Map", "value": coordinates},
                {"name": "Primary_Location", "value": location},
                {"name": "District", "value": "Nanded"},
                {"name": "Street", "value": ""},
                {"name": "Status", "value": ""},
                {"name": "Assigned_To", "value": "425635139776282625"},
                {
                    "name": "Comments",
                    "value": json.dumps({
                        "created": datetime.utcnow().isoformat() + "Z",
                        "comment": "incident created via MCP",
                        "author": "mcp@system",
                        "name": "MCP Bot",
                    }),
                },
                {"name": "Attachments", "value": attachment_id},
            ],
        }
 
        r = requests.post(url, json=body, headers=self._headers())
        r.raise_for_status()
 
        data = r.json()
        print("🚨 Incident created:\n", json.dumps(data, indent=2))
 
        return data