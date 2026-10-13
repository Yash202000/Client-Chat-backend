"""
Integration test for conversation_turn_service (what a phone call says), without audio or LLM keys.

1. IVR-style workflow: greeting + prompt spoken with keypad numbers; keypad digit resumes it.
2. Agent reply path (LLM stubbed): reply is spoken and saved to the conversation.
3. Handoff path (LLM stubbed to request a human): caller marked waiting, AI goes silent.

Creates a temporary workflow / session / call in the dev database and removes them afterwards.
Run from backend/:  python -m scripts.telephony_turn_test [--company-id 1]
"""
import argparse
import asyncio
import json
import sys
import uuid

from app.core.database import SessionLocal
from app.models.agent import Agent
from app.models.call_event import CallEvent
from app.models.chat_message import ChatMessage
from app.models.conversation_session import ConversationSession
from app.models.voice_call import VoiceCall
from app.models.workflow import Workflow
from app.services import agent_execution_service, call_service, conversation_turn_service as turns

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--company-id", type=int, default=1)
args = parser.parse_args()

IVR = {
    "nodes": [
        {"id": "start", "type": "start", "data": {}},
        {"id": "welcome", "type": "response", "data": {"output_value": "Welcome to the test line."}},
        {"id": "menu", "type": "prompt", "data": {"params": {
            "prompt_text": "Which department do you need?",
            "options": [{"key": "sales", "value": "Sales"}, {"key": "support", "value": "Support"}],
        }}},
        {"id": "bye", "type": "response", "data": {"output_value": "Thank you, goodbye."}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "welcome"},
        {"id": "e2", "source": "welcome", "target": "menu"},
        {"id": "e3", "source": "menu", "target": "bye"},
    ],
}

def ivr_flow(open_now: bool):
    """welcome audio -> business hours -> (open) get digits -> transfer | (closed) message + hang up"""
    always = [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "24:00"}]
    return {
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            {"id": "welcome", "type": "play_audio", "data": {"params": {
                "text": "Welcome to our support line.", "audio_url": "https://example.invalid/welcome.wav"}}},
            {"id": "hours", "type": "business_hours", "data": {"params": {
                "timezone": "Asia/Riyadh", "schedule": always if open_now else []}}},
            {"id": "pin", "type": "get_digits", "data": {"params": {
                "prompt_text": "Enter your reference number, then press hash.", "max_digits": 6,
                "terminator": "#", "timeout_seconds": 5, "save_to_variable": "ref"}}},
            {"id": "transfer", "type": "transfer_to_agent", "data": {"params": {
                "text": "Connecting you about reference {{context.ref}}.", "max_wait_seconds": 60,
                "overflow_text": "Please call again later."}}},
            {"id": "closed", "type": "hangup", "data": {"params": {"text": "We are closed. Goodbye."}}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "welcome"},
            {"id": "e2", "source": "welcome", "target": "hours"},
            {"id": "e3", "source": "hours", "sourceHandle": "open", "target": "pin"},
            {"id": "e4", "source": "hours", "sourceHandle": "closed", "target": "closed"},
            {"id": "e5", "source": "pin", "target": "transfer"},
        ],
    }


failures = []


def check(name, condition, detail=""):
    print(f"  {'ok  ' if condition else 'FAIL'} {name}{(' -> ' + str(detail)) if detail and not condition else ''}")
    if not condition:
        failures.append(name)


async def main():
    db = SessionLocal()
    agent = db.query(Agent).filter(Agent.company_id == args.company_id).first()
    tag = uuid.uuid4().hex[:8]
    wf = Workflow(name=f"__telephony_turn_test_{tag}", company_id=args.company_id, visual_steps=json.dumps(IVR),
                  steps={}, is_active=False, version=1)
    db.add(wf); db.commit(); db.refresh(wf)
    sessions = []

    def new_session(suffix):
        conv = ConversationSession(conversation_id=f"voice_test_{tag}_{suffix}", company_id=args.company_id,
                                   channel="voice", agent_id=agent.id if agent else None, status="active",
                                   is_ai_enabled=True)
        db.add(conv); db.commit(); db.refresh(conv)
        sessions.append(conv)
        return conv

    original = agent_execution_service.generate_agent_response
    extra_workflows = []
    try:
        print("0. IVR nodes: audio prompt, business hours, digits, transfer, hang-up")
        for open_now in (True, False):
            w = Workflow(name=f"__telephony_ivr_test_{tag}_{open_now}", company_id=args.company_id,
                         visual_steps=json.dumps(ivr_flow(open_now)), steps={}, is_active=False, version=1)
            db.add(w); db.commit(); db.refresh(w); extra_workflows.append(w)
            conv = new_session(f"ivr_{open_now}")
            out = await turns.run_workflow(db, conv, w.id)
            print(f"   open={open_now} says:", out.say, "expects:", out.expects, "actions:", out.actions)
            check(f"audio prompt carries its file (open={open_now})",
                  {"text": "Welcome to our support line.", "audio_url": "https://example.invalid/welcome.wav"} in out.say, out.say)
            if open_now:
                check("open -> waits for digits", out.expects == "digits" and out.digits["max_digits"] == 6
                      and out.digits["terminator"] == "#", (out.expects, out.digits))
                check("digits question spoken", "Enter your reference number, then press hash." in out.say, out.say)
                out = await turns.handle_turn(db, conv, "123456")
                print("   after digits:", out.say, out.actions)
                check("digits saved and used in transfer message", "Connecting you about reference 123456." in out.say, out.say)
                check("transfer action with overflow", out.actions and out.actions[0]["type"] == "transfer_to_agent"
                      and out.actions[0]["overflow_text"] == "Please call again later.", out.actions)
            else:
                check("closed -> goodbye + hang up", "We are closed. Goodbye." in out.say
                      and out.actions == [{"type": "hangup"}], (out.say, out.actions))

        print("1. IVR workflow + keypad")
        conv = new_session("ivr")
        out = await turns.run_workflow(db, conv, wf.id)
        print("   says:", out.say)
        check("greeting spoken", "Welcome to the test line." in out.say, out.say)
        check("prompt spoken with keypad numbers", any("Press 1 for Sales, 2 for Support" in s for s in out.say), out.say)
        check("waiting for a choice", out.expects == "prompt" and len(out.options) == 2, out)
        key = turns.option_key_for_digit(out.options, "2")
        check("digit 2 -> support", key == "support", key)
        out = await turns.handle_turn(db, conv, "Support", option_key=key)
        print("   says:", out.say)
        check("workflow continues after keypad", out.say == ["Thank you, goodbye."], out.say)
        check("workflow completed", out.workflow_status == "completed", out.workflow_status)

        print("2. Agent reply (LLM stubbed)")
        if not agent:
            check("company has an agent", False, "create an agent for this company")
        else:
            conv = new_session("agent")

            async def fake_reply(db_, agent_id, session_pk, conversation_id, company_id, text, *a, **kw):
                assert kw.get("voice") is True, "voice flag not passed"
                return "We are open from nine to five."
            agent_execution_service.generate_agent_response = fake_reply
            await turns.save_caller_message(db, conv, "When are you open?")
            out = await turns.handle_turn(db, conv, "When are you open?", voice_language="en")
            print("   says:", out.say)
            check("agent reply spoken", out.say == ["We are open from nine to five."], out.say)
            msgs = [(m.sender, m.message) for m in db.query(ChatMessage).filter(ChatMessage.session_id == conv.id).order_by(ChatMessage.id)]
            check("transcript saved (caller + agent)", msgs == [("user", "When are you open?"), ("agent", "We are open from nine to five.")], msgs)

            print("3. Handoff to a human (LLM stubbed to call the handoff tool)")
            conv = new_session("handoff")
            call = VoiceCall(call_sid=f"TEST_{tag}", provider="livekit_sip", room_name=f"call_test_{tag}",
                             from_number="+966500000002", to_number="000999", company_id=args.company_id,
                             conversation_id=conv.conversation_id, status="in_progress", direction="inbound")
            db.add(call); db.commit()

            async def fake_handoff(db_, agent_id, session_pk, conversation_id, company_id, text, *a, **kw):
                from app.services.builtin_tools.handoff import execute_handoff_tool
                result = await execute_handoff_tool(db_, conversation_id, {"reason": "customer_request", "summary": "wants a person"})
                assert result["result"]["status"] == "voice_handoff_requested", result
                return "Of course, please hold while I connect you."
            agent_execution_service.generate_agent_response = fake_handoff
            out = await turns.handle_turn(db, conv, "Let me talk to a person")
            print("   says:", out.say, "handoff:", out.handoff)
            check("handoff flagged", out.handoff is True)
            db.refresh(conv)
            check("session waiting, AI off", conv.waiting_for_agent and not conv.is_ai_enabled, (conv.waiting_for_agent, conv.is_ai_enabled))
            out = await turns.handle_turn(db, conv, "Hello?")
            check("AI silent while waiting for a human", out.say == [], out.say)
            from app.models.user import User
            human = db.query(User).filter(User.company_id == args.company_id, User.is_active.is_(True)).first()
            claimed = call_service.claim_call(db, call.id, args.company_id, human.id)
            check("human can take the waiting AI call", claimed is not None and claimed.handled_by_user_id == human.id)
            check("second claim refused", call_service.claim_call(db, call.id, args.company_id, human.id) is None)
            events = [e.type for e in db.query(CallEvent).filter(CallEvent.call_id == call.id).order_by(CallEvent.seq)]
            check("handoff event recorded", "handoff_requested" in events, events)
    finally:
        agent_execution_service.generate_agent_response = original
        for conv in sessions:
            for c in db.query(VoiceCall).filter(VoiceCall.conversation_id == conv.conversation_id).all():
                db.query(CallEvent).filter(CallEvent.call_id == c.id).delete()
                db.delete(c)
            db.flush()
            db.query(ChatMessage).filter(ChatMessage.session_id == conv.id).delete()
            db.delete(conv)
        from app.models.memory import Memory
        db.query(Memory).filter(Memory.session_id.in_([c.conversation_id for c in sessions])).delete(synchronize_session=False)
        db.delete(wf)
        for w in extra_workflows:
            db.delete(w)
        db.commit(); db.close()

    print("RESULT", "PASS" if not failures else f"FAIL ({', '.join(failures)})")
    return not failures


sys.exit(0 if asyncio.run(main()) else 1)
