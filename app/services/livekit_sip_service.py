"""
LiveKit SIP provisioning for contact-centre phone numbers.

Each active PhoneNumber gets its own LiveKit inbound trunk and an "individual" dispatch rule:
every inbound call lands in a new room (TELEPHONY_ROOM_PREFIX + random suffix). For routing_mode
"ai" the AgentConnect voice process (TELEPHONY_VOICE_AGENT_NAME) is dispatched into it with the
phone number's ids as job metadata; "direct" numbers ring human agents instead (see call_service). LiveKit ids are kept in PhoneNumber.provider_config.
"""
import json
import logging
from typing import Optional

from google.protobuf.duration_pb2 import Duration
from livekit import api

from app.core.config import settings
from app.models.phone_number import PhoneNumber

logger = logging.getLogger(__name__)


def _api() -> api.LiveKitAPI:
    from app.services import livekit_nodes

    url = livekit_nodes.api_url()
    if not (url and settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET):
        raise RuntimeError("LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET are not configured")
    return api.LiveKitAPI(url, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)


def _allowed_addresses() -> list[str]:
    return [a.strip() for a in settings.TELEPHONY_SIP_ALLOWED_ADDRESSES.split(",") if a.strip()]


def _dispatch_metadata(phone: PhoneNumber) -> str:
    return json.dumps({"company_id": phone.company_id, "phone_number_id": phone.id, "number": phone.number})


async def sync_phone_number(phone: PhoneNumber) -> dict:
    """Create or replace the LiveKit trunk + dispatch rule for a number. Returns the new provider_config."""
    config = dict(phone.provider_config or {})
    lk = _api()
    try:
        # Replace rather than patch: simpler and keeps LiveKit in step with our settings.
        await _delete_resources(lk, config)
        config.pop("inbound_trunk_id", None)
        config.pop("dispatch_rule_id", None)
        if not phone.is_active:
            return config

        trunk = await lk.sip.create_sip_inbound_trunk(api.CreateSIPInboundTrunkRequest(
            trunk=api.SIPInboundTrunkInfo(
                name=f"agentconnect-{phone.company_id}-{phone.number}",
                numbers=[phone.number],
                allowed_addresses=_allowed_addresses(),
                auth_username=settings.TELEPHONY_SIP_AUTH_USERNAME,
                auth_password=settings.TELEPHONY_SIP_AUTH_PASSWORD,
                metadata=_dispatch_metadata(phone),
                ringing_timeout=Duration(seconds=settings.TELEPHONY_RINGING_TIMEOUT_SECONDS),
            )
        ))
        config["inbound_trunk_id"] = trunk.sip_trunk_id

        rule = await lk.sip.create_sip_dispatch_rule(api.CreateSIPDispatchRuleRequest(
            name=f"agentconnect-{phone.company_id}-{phone.number}",
            trunk_ids=[trunk.sip_trunk_id],
            rule=api.SIPDispatchRule(
                dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix=settings.TELEPHONY_ROOM_PREFIX)
            ),
            metadata=_dispatch_metadata(phone),
            attributes={
                "agentconnect.company_id": str(phone.company_id),
                "agentconnect.phone_number_id": str(phone.id),
            },
            # "direct" numbers ring human agents' browsers; only "ai" numbers get the voice process
            room_config=api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(
                    agent_name=settings.TELEPHONY_VOICE_AGENT_NAME,
                    metadata=_dispatch_metadata(phone),
                )] if phone.routing_mode == "ai" else [],
            ),
        ))
        config["dispatch_rule_id"] = rule.sip_dispatch_rule_id
        return config
    finally:
        await lk.aclose()


async def delete_phone_number_resources(phone: PhoneNumber) -> None:
    lk = _api()
    try:
        await _delete_resources(lk, phone.provider_config or {})
    finally:
        await lk.aclose()


async def _delete_resources(lk: api.LiveKitAPI, config: dict) -> None:
    rule_id: Optional[str] = config.get("dispatch_rule_id")
    trunk_id: Optional[str] = config.get("inbound_trunk_id")
    if rule_id:
        try:
            await lk.sip.delete_sip_dispatch_rule(api.DeleteSIPDispatchRuleRequest(sip_dispatch_rule_id=rule_id))
        except api.TwirpError as e:
            logger.warning(f"[livekit-sip] dispatch rule {rule_id} not deleted: {e.message}")
    if trunk_id:
        try:
            await lk.sip.delete_sip_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=trunk_id))
        except api.TwirpError as e:
            logger.warning(f"[livekit-sip] trunk {trunk_id} not deleted: {e.message}")


async def status() -> dict:
    lk = _api()
    try:
        trunks = await lk.sip.list_sip_inbound_trunk(api.ListSIPInboundTrunkRequest())
        rules = await lk.sip.list_sip_dispatch_rule(api.ListSIPDispatchRuleRequest())
        return {"inbound_trunks": len(trunks.items), "dispatch_rules": len(rules.items)}
    finally:
        await lk.aclose()
