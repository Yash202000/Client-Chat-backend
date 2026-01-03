"""
WhatsApp Token Service for managing OAuth token exchange and refresh.

Supports:
- Short-lived to long-lived token exchange
- Automatic token refresh before expiry
- Backward compatibility with legacy access tokens
"""
import httpx
import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

from app.models import integration as models_integration
from app.services import integration_service
from app.services.vault_service import vault_service

logger = logging.getLogger(__name__)

# Meta Graph API configuration
META_GRAPH_API_VERSION = "v19.0"
META_OAUTH_ENDPOINT = f"https://graph.facebook.com/{META_GRAPH_API_VERSION}/oauth/access_token"

# Token expiry configuration
SHORT_LIVED_TOKEN_EXPIRY_SECONDS = 3600  # ~1 hour
LONG_LIVED_TOKEN_EXPIRY_SECONDS = 60 * 24 * 3600  # ~60 days
REFRESH_BUFFER_SECONDS = 300  # Refresh 5 minutes before expiry
PROACTIVE_REFRESH_THRESHOLD_DAYS = 7  # Refresh long-lived tokens 7 days before expiry


class WhatsAppTokenError(Exception):
    """Custom exception for WhatsApp token operations."""
    pass


class WhatsAppTokenService:
    """
    Service for managing WhatsApp Business API OAuth tokens.

    Supports:
    - Short-lived to long-lived token exchange
    - Automatic token refresh before expiry
    - Backward compatibility with legacy access tokens
    """

    async def exchange_for_long_lived_token(
        self,
        short_lived_token: str,
        client_id: str,
        client_secret: str
    ) -> Tuple[str, int]:
        """
        Exchange a short-lived token for a long-lived token.

        Args:
            short_lived_token: The short-lived access token
            client_id: Meta App ID
            client_secret: Meta App Secret

        Returns:
            Tuple of (new_access_token, expires_in_seconds)

        Raises:
            WhatsAppTokenError: If token exchange fails
        """
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "fb_exchange_token": short_lived_token
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(META_OAUTH_ENDPOINT, params=params, timeout=30.0)
                response.raise_for_status()
                data = response.json()

                access_token = data.get("access_token")
                expires_in = data.get("expires_in", LONG_LIVED_TOKEN_EXPIRY_SECONDS)

                if not access_token:
                    raise WhatsAppTokenError("No access_token in response")

                logger.info(f"Successfully exchanged for long-lived token (expires in {expires_in}s)")
                return access_token, expires_in

            except httpx.HTTPStatusError as e:
                error_detail = e.response.text
                logger.error(f"Failed to exchange token: {error_detail}")
                raise WhatsAppTokenError(f"Token exchange failed: {error_detail}")
            except httpx.RequestError as e:
                logger.error(f"Request error during token exchange: {e}")
                raise WhatsAppTokenError(f"Request error: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error during token exchange: {e}")
                raise WhatsAppTokenError(f"Unexpected error: {str(e)}")

    async def refresh_token(
        self,
        current_token: str,
        client_id: str,
        client_secret: str
    ) -> Tuple[str, int]:
        """
        Refresh a long-lived token using the same exchange endpoint.
        Meta allows refreshing long-lived tokens before they expire.

        Args:
            current_token: The current long-lived access token
            client_id: Meta App ID
            client_secret: Meta App Secret

        Returns:
            Tuple of (new_access_token, expires_in_seconds)
        """
        # Meta uses the same endpoint for refresh as for exchange
        return await self.exchange_for_long_lived_token(
            short_lived_token=current_token,
            client_id=client_id,
            client_secret=client_secret
        )

    def get_credentials_with_expiry_check(
        self,
        integration: models_integration.Integration
    ) -> Dict[str, Any]:
        """
        Get decrypted credentials and check if they need refresh.

        Args:
            integration: The WhatsApp integration

        Returns:
            Dict with credentials and additional flags:
            - is_oauth_enabled: bool
            - needs_refresh: bool
        """
        credentials = integration_service.get_decrypted_credentials(integration)

        # Check if OAuth is enabled
        is_oauth_enabled = bool(
            credentials.get("client_id") and
            credentials.get("client_secret")
        )

        needs_refresh = False
        if is_oauth_enabled and credentials.get("token_expires_at"):
            expires_at = credentials["token_expires_at"]
            current_time = datetime.utcnow().timestamp()
            needs_refresh = (expires_at - current_time) <= REFRESH_BUFFER_SECONDS

        return {
            **credentials,
            "is_oauth_enabled": is_oauth_enabled,
            "needs_refresh": needs_refresh
        }

    async def ensure_valid_token(
        self,
        db: Session,
        integration: models_integration.Integration
    ) -> str:
        """
        Ensure the integration has a valid token, refreshing if necessary.

        This is the main method to call before making API requests.

        Args:
            db: Database session
            integration: The WhatsApp integration

        Returns:
            A valid access token
        """
        credentials = self.get_credentials_with_expiry_check(integration)

        # Get current token
        current_token = credentials.get("access_token") or credentials.get("api_token")

        # If no OAuth or token doesn't need refresh, return current token
        if not credentials["is_oauth_enabled"] or not credentials["needs_refresh"]:
            return current_token

        # Attempt to refresh the token
        try:
            logger.info(f"Refreshing token for integration {integration.id}")

            new_token, expires_in = await self.refresh_token(
                current_token=current_token,
                client_id=credentials["client_id"],
                client_secret=credentials["client_secret"]
            )

            # Update credentials with new token
            updated_credentials = {
                **credentials,
                "access_token": new_token,
                "token_type": "long_lived",
                "token_expires_at": int(datetime.utcnow().timestamp() + expires_in),
                "last_refresh_at": int(datetime.utcnow().timestamp()),
                "refresh_error": None
            }

            # Remove internal flags before saving
            updated_credentials.pop("is_oauth_enabled", None)
            updated_credentials.pop("needs_refresh", None)

            # Update integration in database
            self._update_integration_credentials(db, integration, updated_credentials)

            logger.info(f"Successfully refreshed token for integration {integration.id}")
            return new_token

        except WhatsAppTokenError as e:
            # Log the error but return current token (may still work briefly)
            logger.error(f"Failed to refresh token for integration {integration.id}: {e}")

            # Update credentials with error info
            updated_credentials = {
                **credentials,
                "refresh_error": str(e)
            }
            updated_credentials.pop("is_oauth_enabled", None)
            updated_credentials.pop("needs_refresh", None)

            self._update_integration_credentials(db, integration, updated_credentials)

            return current_token

    def _update_integration_credentials(
        self,
        db: Session,
        integration: models_integration.Integration,
        credentials: Dict[str, Any]
    ) -> None:
        """
        Update integration credentials in the database.

        Args:
            db: Database session
            integration: The integration to update
            credentials: New credentials dict
        """
        credentials_json = json.dumps(credentials)
        integration.credentials = vault_service.encrypt(credentials_json)
        db.commit()
        db.refresh(integration)

    def is_token_expiring_soon(
        self,
        credentials: Dict[str, Any],
        threshold_days: int = PROACTIVE_REFRESH_THRESHOLD_DAYS
    ) -> bool:
        """
        Check if token is expiring within the threshold period.
        Used for proactive background refresh.

        Args:
            credentials: Decrypted credentials dict
            threshold_days: Number of days before expiry to consider "expiring soon"

        Returns:
            True if token expires within threshold_days
        """
        if not credentials.get("token_expires_at"):
            return False

        expires_at = credentials["token_expires_at"]
        current_time = datetime.utcnow().timestamp()
        threshold_seconds = threshold_days * 24 * 3600

        return (expires_at - current_time) <= threshold_seconds


# Singleton instance
whatsapp_token_service = WhatsAppTokenService()
