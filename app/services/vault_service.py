from cryptography.fernet import Fernet
from app.core.config import settings

# This is a simple implementation for demonstration purposes. 
# In a production environment, use a more robust key management system.

# Ensure you have a secret key in your environment or config.
# For example, you can generate one using: Fernet.generate_key().decode()
SECRET_KEY = settings.SECRET_KEY
if not SECRET_KEY:
    raise ValueError("SECRET_KEY is not set in the environment variables.")

cipher_suite = Fernet(SECRET_KEY.encode())

def encrypt_data(data: str) -> str:
    """Encrypts a string."""
    if not data:
        return data
    return cipher_suite.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    """Decrypts a string."""
    if not encrypted_data:
        return encrypted_data
    return cipher_suite.decrypt(encrypted_data.encode()).decode()

def encrypt_dict(data_dict: dict) -> dict:
    """Encrypts all values in a dictionary."""
    if not data_dict:
        return {}
    return {key: encrypt_data(value) for key, value in data_dict.items()}

def decrypt_dict(encrypted_dict: dict) -> dict:
    """Decrypts all values in a dictionary."""
    if not encrypted_dict:
        return {}
    return {key: decrypt_data(value) for key, value in encrypted_dict.items()}
