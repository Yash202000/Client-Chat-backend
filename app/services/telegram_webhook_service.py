import httpx

from app.core.config import settings


class TelegramWebhookService:
    TELEGRAM_API_BASE = "https://api.telegram.org/bot"
    
    async def register_webhook(
        self, 
        bot_token: str, 
        integration_id: int,
        backend_url: str = None
    ) -> dict:
        backend_url = backend_url or settings.BACKEND_URL
        
        if not backend_url:
            raise Exception("BACKEND_URL is not configured. Cannot register Telegram webhook.")
        
        # webhook_url = f"{backend_url.rstrip('/')}/api/v1/telegram/webhook/{integration_id}"
        webhook_url = f"{backend_url.rstrip('/')}/api/v1/webhooks/telegram/webhook/{integration_id}"
        api_url = f"{self.TELEGRAM_API_BASE}{bot_token}/setWebhook"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                api_url,
                data={
                    "url": webhook_url,
                    "allowed_updates": []
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30.0
            )
            
            result = response.json()
            
            if not result.get("ok"):
                error_desc = result.get("description", "Unknown error")
                raise Exception(f"Telegram API error: {error_desc}")
            
            return {
                "status": "success",
                "webhook_url": webhook_url,
                "telegram_response": result
            }
    
    async def delete_webhook(self, bot_token: str) -> dict:
        api_url = f"{self.TELEGRAM_API_BASE}{bot_token}/deleteWebhook"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(api_url, timeout=30.0)
            return response.json()
    
    async def get_webhook_info(self, bot_token: str) -> dict:
        api_url = f"{self.TELEGRAM_API_BASE}{bot_token}/getWebhookInfo"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, timeout=30.0)
            return response.json()
