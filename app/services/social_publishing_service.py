import json
import logging
from datetime import datetime
from typing import List, Optional
import httpx
from sqlalchemy.orm import Session

from app.models.social_post import SocialPost, PostStatus
from app.models.social_account import SocialPlatform
from app.services.vault_service import vault_service
from app.core.config import settings

logger = logging.getLogger(__name__)


class SocialPublishingService:

    async def publish_post_to_platform(self, db: Session, post: SocialPost) -> dict:
        """Publish a post to its target platform. Updates post status in DB."""
        post.status = PostStatus.PUBLISHING
        db.commit()

        try:
            account = post.social_account
            creds_json = vault_service.decrypt(account.credentials)
            creds = json.loads(creds_json)

            full_content = post.content or ""
            if post.hashtags:
                tag_str = " ".join(f"#{t.lstrip('#')}" for t in post.hashtags)
                full_content = f"{full_content}\n\n{tag_str}"

            if post.platform == SocialPlatform.LINKEDIN:
                result = await self._publish_to_linkedin(creds, full_content, post.media_urls, account.account_id)
            elif post.platform == SocialPlatform.INSTAGRAM:
                result = await self._publish_to_instagram(creds, full_content, post.media_urls)
            elif post.platform == SocialPlatform.FACEBOOK:
                result = await self._publish_to_facebook(creds, full_content, post.media_urls)
            else:
                raise ValueError(f"Unsupported platform: {post.platform}")

            post.status = PostStatus.PUBLISHED
            post.published_at = datetime.utcnow()
            post.platform_post_id = result.get("id") or result.get("post_id")
            post.error_message = None

        except Exception as e:
            logger.error(f"Failed to publish post {post.id}: {e}")
            post.status = PostStatus.FAILED
            post.error_message = str(e)

        post.updated_at = datetime.utcnow()
        db.commit()
        return {"status": post.status, "platform_post_id": post.platform_post_id}

    async def get_posts_due_for_publishing(self, db: Session) -> List[SocialPost]:
        """Return scheduled posts whose scheduled_at is now or in the past."""
        return (
            db.query(SocialPost)
            .filter(
                SocialPost.status == PostStatus.SCHEDULED,
                SocialPost.scheduled_at <= datetime.utcnow(),
            )
            .all()
        )

    async def refresh_analytics(self, db: Session, post: SocialPost):
        """Fetch latest engagement metrics from the platform and update the post."""
        if not post.platform_post_id or post.status != PostStatus.PUBLISHED:
            return

        account = post.social_account
        creds_json = vault_service.decrypt(account.credentials)
        creds = json.loads(creds_json)
        access_token = creds.get("access_token")

        try:
            if post.platform == SocialPlatform.LINKEDIN:
                await self._refresh_linkedin_analytics(post, access_token)
            elif post.platform == SocialPlatform.FACEBOOK:
                await self._refresh_facebook_analytics(post, creds)
            elif post.platform == SocialPlatform.INSTAGRAM:
                await self._refresh_instagram_analytics(post, creds)
        except Exception as e:
            logger.warning(f"Could not refresh analytics for post {post.id}: {e}")

        post.analytics_updated_at = datetime.utcnow()
        db.commit()

    # -----------------------------------------------------------------------
    # Platform-specific publishing
    # -----------------------------------------------------------------------

    async def _publish_to_linkedin(self, creds: dict, content: str, media_urls: Optional[list], member_id: str) -> dict:
        """Publish a post to LinkedIn via UGC Posts API."""
        access_token = creds.get("access_token")
        author_urn = f"urn:li:person:{member_id}"

        payload = {
            "author": author_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": content},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.linkedin.com/v2/ugcPosts",
                json=payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                timeout=30,
            )
            if not resp.is_success:
                logger.error(f"LinkedIn ugcPosts error {resp.status_code}: {resp.text}")
            resp.raise_for_status()
            data = resp.json()
            return {"id": data.get("id")}

    async def _publish_to_instagram(self, creds: dict, content: str, media_urls: Optional[list]) -> dict:
        """Publish to Instagram Business account via Graph API (2-step)."""
        access_token = creds.get("access_token")
        ig_user_id = creds.get("ig_user_id")
        version = settings.INSTAGRAM_GRAPH_API_VERSION

        image_url = media_urls[0] if media_urls else None

        async with httpx.AsyncClient() as client:
            # Step 1: Create media container
            container_params: dict = {
                "caption": content,
                "access_token": access_token,
            }
            if image_url:
                container_params["image_url"] = image_url
                container_params["media_type"] = "IMAGE"
            else:
                # Text-only not supported on Instagram — use a placeholder approach
                raise ValueError(
                    "Instagram requires at least one image. Please add an image to publish."
                )

            container_resp = await client.post(
                f"https://graph.facebook.com/{version}/{ig_user_id}/media",
                params=container_params,
                timeout=30,
            )
            container_resp.raise_for_status()
            creation_id = container_resp.json().get("id")

            # Step 2: Publish the container
            publish_resp = await client.post(
                f"https://graph.facebook.com/{version}/{ig_user_id}/media_publish",
                params={"creation_id": creation_id, "access_token": access_token},
                timeout=30,
            )
            publish_resp.raise_for_status()
            return {"id": publish_resp.json().get("id")}

    async def _publish_to_facebook(self, creds: dict, content: str, media_urls: Optional[list]) -> dict:
        """Publish a post to a Facebook Page."""
        access_token = creds.get("access_token")
        page_id = creds.get("page_id")

        params: dict = {"message": content, "access_token": access_token}
        if media_urls:
            params["link"] = media_urls[0]

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://graph.facebook.com/v19.0/{page_id}/feed",
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            return {"id": resp.json().get("id")}

    # -----------------------------------------------------------------------
    # Analytics refresh
    # -----------------------------------------------------------------------

    async def _refresh_linkedin_analytics(self, post: SocialPost, access_token: str):
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.linkedin.com/v2/socialActions/{post.platform_post_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                post.likes = data.get("likesSummary", {}).get("totalLikes", post.likes)
                post.comments = data.get("commentsSummary", {}).get("totalFirstLevelComments", post.comments)

    async def _refresh_facebook_analytics(self, post: SocialPost, creds: dict):
        access_token = creds.get("access_token")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://graph.facebook.com/v19.0/{post.platform_post_id}",
                params={
                    "fields": "likes.summary(true),comments.summary(true),shares",
                    "access_token": access_token,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                post.likes = data.get("likes", {}).get("summary", {}).get("total_count", post.likes)
                post.comments = data.get("comments", {}).get("summary", {}).get("total_count", post.comments)
                post.shares = data.get("shares", {}).get("count", post.shares)

    async def _refresh_instagram_analytics(self, post: SocialPost, creds: dict):
        access_token = creds.get("access_token")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://graph.facebook.com/v19.0/{post.platform_post_id}",
                params={
                    "fields": "like_count,comments_count",
                    "access_token": access_token,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                post.likes = data.get("like_count", post.likes)
                post.comments = data.get("comments_count", post.comments)
