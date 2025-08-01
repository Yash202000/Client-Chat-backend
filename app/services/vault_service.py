import os
from cryptography.fernet import Fernet
from app.core.config import settings

class VaultService:
    def __init__(self):
        # In a real production environment, the key should be loaded from a secure
        # location (like a secret manager) and not hardcoded or stored in a .env file.
        # For this project, we'll use the SECRET_KEY from the settings.
        key = settings.SECRET_KEY.encode()
        if len(key) < 32:
            key = key.ljust(32, b'\0')
        elif len(key) > 32:
            key = key[:32]
        
        # Fernet keys must be 32 url-safe base64-encoded bytes.
        # We'll use the SECRET_KEY and ensure it's the correct length.
        # A more robust solution would generate a dedicated encryption key.
        from base64 import urlsafe_b64encode
        self.key = urlsafe_b64encode(key)
        self.fernet = Fernet(self.key)

    def encrypt(self, data: str) -> bytes:
        """Encrypts a string and returns bytes."""
        if not data:
            return None
        return self.fernet.encrypt(data.encode())

    def decrypt(self, encrypted_data: bytes) -> str:
        """Decrypts bytes and returns a string."""
        if not encrypted_data:
            return None
        return self.fernet.decrypt(encrypted_data).decode()

vault_service = VaultService()