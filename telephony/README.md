# Contact centre telephony (LiveKit SIP)

Self-hosted telephony for HeyGenAlly: calls arrive over SIP, LiveKit turns each call into a room,
and the AgentConnect voice process joins it. Plan: `../../LIVEKIT_SIP_CONTACT_CENTER_PLAN.md`. All commands below run from `backend/`.

```
softphone / SIP trunk ──SIP──▶ LiveKit SIP ──▶ room call_<caller>_<id>
                                                 ├─ caller (SIP participant)
                                                 └─ voice process "agentconnect-voice" (backend/app/agents/contact_center_agent.py)
LiveKit webhooks ──▶ backend /api/v1/telephony/livekit/webhook
voice process ──Redis pub/sub──▶ backend websockets ──▶ dashboards
```

Linux host required (host networking for media ports).

## 1. Start the stack

```bash
cd backend
docker compose up -d redis livekit livekit-sip livekit-egress   # from backend/docker-compose.yml
docker compose ps
# (or the standalone file: docker compose -f telephony/docker-compose.yml up -d — not both)
```

Recordings are uploaded by Egress straight to MinIO / S3 using the backend's `MINIO_*` settings
(`call-recordings/<company>/<yyyy>/<mm>/<dd>/call-<id>.ogg`). The Egress image is large (~1.5 GB).

| Service | Ports on the host |
|---|---|
| Redis (persistent: holds LiveKit trunks + rules) | 6379 |
| LiveKit server | 7880 (API/WS), 7881 TCP, 50000–60000 UDP |
| LiveKit SIP | 5060 UDP/TCP, 10000–20000 UDP (RTP) |

Open those ports in the host firewall if a softphone on another device will call in.

## 2. Point the backend at it

In `backend/.env` (the dev keys are in `livekit.yaml`; change them for any shared environment):

```
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=agentconnect_dev_secret_change_me_0123456789
REDIS_URL=redis://localhost:6379/0
```

Agents on other devices need `LIVEKIT_PUBLIC_URL=ws://<host-ip>:7880` (the URL their browser uses).
Size `TELEPHONY_VOICE_IDLE_PROCESSES` to the peak number of simultaneous AI / IVR calls.

Note: internal video calls use the same LiveKit settings, so they will also use this local server.
The frontend's `VITE_LIVEKIT_URL` should then be `ws://<host-ip>:7880`.

Restart the backend, then start the voice process:

```bash
source venv/bin/activate
python -m app.agents.contact_center_agent dev      # dev; use "start" in production
# or in Docker (uses .env): docker compose --profile voice up -d voice-agent
```

Wait for `[prewarm] job process ready` (≈15 s: it preloads the backend so calls answer in ~1 s).

## 3. Add a number

Settings → Voice → **Contact Center Numbers** → Add number, e.g. `980`.
Saving creates a LiveKit inbound trunk + dispatch rule; the row shows **Live** when synced.

After wiping LiveKit/Redis, restore every number with:

```bash
python -m scripts.telephony_sync
```

## 4a. Softphones that log in (PortSIP, Zoiper, …) — SIP registrar

LiveKit SIP doesn't accept softphone logins (REGISTER → 405). The `sip-registrar` service
(Kamailio, `telephony/kamailio/`) does, using **HeyGenAlly users' SIP accounts**:

1. `docker compose up -d sip-registrar` (built from `telephony/kamailio`; reads `.env`).
2. Contact Center → **SIP phones** → *Set up* a user: SIP username + password (stored only as the SIP
   digest hash). Only active users with an enabled account can sign in; disabling takes effect at once.
3. In the softphone: SIP server/domain `192.168.31.107`, port `5080`, transport UDP or TCP (TLS on 5081 when enabled, see below),
   username/password as set. DTMF: RFC 2833.
4. Dial a contact-centre number (e.g. `980`) — the caller shows as the SIP username — or another
   user's SIP username to call their softphone directly.

Settings: `TELEPHONY_SIP_REGISTRAR_ADDRESS` (address softphones use; the registrar listens there) and
`TELEPHONY_SIP_REALM` (changing the realm requires setting the SIP passwords again).
Test without a phone: `python -m scripts.sip_registrar_test`.

### Deploying the registrar (image `agentconnect-sip-registrar`)

Everything is in `telephony/kamailio/`. The image is configured only by environment variables (listed at
the top of `entrypoint.sh`), runs as a non-root user and has a health check.

1. **Build** (version in `VERSION`):
   ```bash
   telephony/kamailio/build.sh                              # agentconnect-sip-registrar:1.0.0 + :latest
   REGISTRY=<your-registry>/agentconnect telephony/kamailio/build.sh 1.0.0 --push
   telephony/kamailio/build.sh 1.0.0 --save                 # .tar.gz for servers without a registry
   ```
   On the server: `docker load -i agentconnect-sip-registrar-1.0.0.tar.gz`.
2. **Database login (read-only)**. As the DB owner, run once:
   `psql <db-url> -v pw="'<strong-password>'" -f telephony/kamailio/readonly-role.sql`
   This creates role `sip_registrar`, which can read only the `kamailio_subscriber` view.
3. **Configure**: `cp registrar.env.example registrar.env`, then set:
   - `TELEPHONY_SIP_REGISTRAR_ADDRESS` (public IP or DNS name + port; same value as the backend)
   - `TELEPHONY_SIP_REALM`
   - `KAMAILIO_DB_URL`
   - `LIVEKIT_SIP_ADDRESS`

   Cloud or NAT servers: the registrar binds the local IP (`SIP_LISTEN_IP`, detected automatically) and
   advertises the public address. A DNS name must resolve from inside the container.
4. **Run**: `docker compose -f docker-compose.deploy.yml up -d` (host networking, read-only filesystem,
   all capabilities dropped).
5. **Firewall**: open 5080/udp+tcp (5081/tcp with TLS) to the softphones. Audio does not pass through the
   registrar. LiveKit SIP must accept calls from the registrar's IP (`TELEPHONY_SIP_ALLOWED_ADDRESSES`) and
   expose its RTP range.

**TLS (optional)**: mount a certificate and set `SIP_TLS_CERT` / `SIP_TLS_KEY`. The files must be readable
by uid 100. The registrar then also listens on `SIP_TLS_PORT` (5081). In PortSIP choose transport TLS,
port 5081.

**Protection when exposed to the internet**:
- After `SIP_MAX_AUTH_FAILURES` (10) wrong passwords or unknown users, an IP is blocked for
  `SIP_BAN_SECONDS` (900).
- More than `SIP_FLOOD_REQUESTS` (60) requests in 2 seconds also blocks the IP.
- Known SIP scanners are dropped.
- LiveKit SIP's IP is never blocked.
- Blocks are logged as `SECURITY: … blocked`.

To lift a block early:
```bash
docker exec <container> kamcmd -s unix:/run/kamailio/kamailio_ctl htable.delete ipban <ip>
```

### High availability

Optional, chosen per deployment by settings only. Local development stays single node: leave
`LIVEKIT_URLS`, `REDIS_SENTINELS` and `SIP_PEERS` empty (the default). For HA: two registrars sharing registrations in the database, two LiveKit / LiveKit SIP / Egress nodes and Redis
Sentinel: see [HA.md](HA.md). Lab on one machine: `telephony/ha/`, tests `scripts/telephony_ha_test.py`,
`scripts/sip_registrar_ha_test.py`.

### When do I need to rebuild?

Rarely. Rebuild only when the registrar's own files in `telephony/kamailio/` change.

| What changes | What to do |
|---|---|
| A user gets a SIP login, changes the password, is disabled or deactivated | Nothing. Logins are read from the database every time. |
| A setting (address, realm, LiveKit address, block limits, TLS certificate) | Edit `registrar.env` (or `.env` locally), then `docker compose up -d sip-registrar`. No rebuild. |
| Backend or frontend code | Nothing. The registrar is a separate image. |
| `kamailio.cfg.tpl`, `entrypoint.sh`, `healthcheck.sh` or `Dockerfile` | Bump `VERSION`, run `build.sh <version>`, then update the image tag in the compose file. |

- **Locally**: `docker compose up -d sip-registrar` uses the image that is already built. After changing
  registrar files, run `docker compose build sip-registrar` first.
- **Getting a new version onto a server**: do this once per version, not on every deploy.
  - With a container registry: `REGISTRY=… build.sh <version> --push`, then the server pulls the image.
  - Without a registry: `build.sh <version> --save`, copy the `.tar.gz` to the server, then `docker load -i …`.

## 4. Call it from a softphone (no telecom provider needed)

Any free softphone works (MicroSIP, Linphone, Zoiper). No account or registration — dial by IP:

```
sip:980@<host-LAN-ip>          e.g. sip:980@192.168.31.107
```

- **DTMF mode: RFC 2833 / "RTP events"** — otherwise keypad presses are not detected.
- To pretend to be different callers, set the softphone's user / display name, e.g. `+966501234567`.
- `TELEPHONY_SIP_ALLOWED_ADDRESSES` (backend `.env`) restricts which IPs may call in; empty = anyone (dev only).
  Re-sync numbers after changing it.

**What to expect in M0:** the call is answered, you hear "Welcome to HeyGenAlly…" (needs a valid
`OPENAI_API_KEY`; otherwise the call is silent but still connected), each key press is read back,
and the voice process log shows `[call] connected` and `DTMF` lines. With `REDIS_URL` set, browsers
connected to the company websocket receive `voice_call_started`, `voice_call_dtmf`, `voice_call_ended`.

## 5. Automated checks (no softphone)

| Script | What it checks |
|---|---|
| `python -m scripts.telephony_loopback_test --sip-host <ip> --mode ai` | AI-answered call, keypad, call record + events |
| `… --mode ivr` | entry workflow collects 3 digits then hangs up (needs valid speech keys) |
| `… --mode direct --api-url <backend> --user-email <agent>` | ring agents, first accept wins, browser-style join, hangup |
| `… --mode queue …` | queue offer → accept → hold / resume → hangup → wrap-up → ready |
| `… --mode transfer … --user2-email <agent2>` | blind transfer A → B, supervisor listen, transfer chain, recording + permissions |
| `python -m scripts.telephony_turn_test` | conversation turns: IVR nodes, agent replies, handoff (no audio) |
| `python -m scripts.telephony_acd_test` | queues, agent states, wrap-up, shifts, manual records, transfer rules (no audio) |
| `python -m scripts.telephony_m9_test` | wait time estimate + announcement text; recording pause / resume through Egress into MinIO (parts, audit) |
| `python -m scripts.tts_prompt_test [--live]` | pre-generated IVR prompts: fixed texts found, stored once in MinIO, played instead of live speech |
| `python -m scripts.permissions_test` | audit log, security logs, data export, settings / ticket admin endpoints refuse users without the permission |

### Loopback details

LiveKit SIP can call itself: a temporary outbound trunk pointing at its own SIP port dials a
temporary test number, which loops back into the inbound side. This exercises
SIP → dispatch → voice process → DB → Redis → DTMF → hang-up, then removes everything it created.

```bash
python -m scripts.telephony_loopback_test --sip-host <host-LAN-ip>
# answered in 1.2s ... EVENT TYPES ['voice_call_started', 'voice_call_dtmf', 'voice_call_ended']
# RESULT PASS
```

Needs the stack, `REDIS_URL` and a running voice process. SIPp scenarios for load tests come in M6.

## Pre-generated prompts (fixed IVR text)

Fixed texts a caller can hear — node text in a number's entry workflow and its sub-workflows (response,
play_audio, prompt + keypad options, get_digits, listen, transfer / overflow, hang-up), the Agent's welcome
message, and the greeting / hold phrases — are turned into speech once and stored in MinIO
(`tts-prompts/<company>/<sha256>.<mp3|wav|ogg>`, table `tts_prompts`). Calls play the stored file; anything else
(AI replies, text with `{{placeholders}}`) is spoken live. Recorded prompts (`audio_url`) always win.

- Refreshed automatically (background) when a workflow, phone number or the Agent's voice / welcome / language changes.
  Editing a text or changing the voice creates a new file and removes the old one.
- Status: `GET /api/v1/telephony/tts-prompts`; generate now / retry failed: `POST /api/v1/telephony/tts-prompts/sync`
  or `python -m scripts.tts_prompt_sync [--company-id N]` (e.g. after the provider was down or a key was fixed).
- **Provider / voice**: calls (live speech, stored prompts and hold messages) use the number's Agent's TTS provider +
  voice through the shared `TTSService` (`openai`, `localai`, `voice_engine`, `groq`). Groq picks its model from the text:
  Arabic script → `GROQ_TTS_MODEL_AR` (Orpheus Saudi Arabic), otherwise `GROQ_TTS_MODEL_EN`; voice `default` →
  `GROQ_TTS_VOICE_AR` / `GROQ_TTS_VOICE_EN`. The Groq org admin must accept each model's terms in the Groq console once. Check and change it in
  Contact Center → **Voice prompts** (with Preview) or Agent settings → Voice Configuration. Numbers without an
  Agent use `TELEPHONY_TTS_DEFAULT_PROVIDER`.
- Settings: `TELEPHONY_TTS_CACHE` (on/off), `TELEPHONY_TTS_DEFAULT_PROVIDER`.

## Understanding the caller (speech-to-text)

Callers can talk over a prompt (it stops) and answer by voice: a prompt menu matches the spoken option name,
a Listen node stores the answer, after the workflow the Agent replies. Get-digits nodes are keypad only.

- Calls listen with the number's Agent **STT provider** (`deepgram`, `openai`, `groq` Whisper, `localai` Whisper —
  no key, phone calls only); numbers without an Agent use `TELEPHONY_STT_DEFAULT_PROVIDER` (groq). Change it in
  Contact Center → **Voice prompts** ("Listens with") or Agent settings → STT Provider.
- No key for that provider → the call runs **keypad only** (event `stt_unavailable`; noise doesn't cut prompts).
  A key that is set but rejected still fails mid-call → handed to a human (`ai_failed`).
- Settings: `GROQ_STT_MODEL`, `OPENAI_STT_MODEL`, `TELEPHONY_DEEPGRAM_MODEL`, `LOCALAI_STT_URL`, `LOCALAI_STT_MODEL`.
- Check: `python -m scripts.phone_stt_test [--stt groq localai deepgram openai]` (speaks a sentence, transcribes it).

## Troubleshooting

| Symptom | Check |
|---|---|
| Softphone gets 404 / no answer | Number synced (**Live** badge)? `/api/v1/telephony/status` shows trunks ≥ 1? |
| 403 from LiveKit SIP | Your IP not in `TELEPHONY_SIP_ALLOWED_ADDRESSES` |
| Answered but silent | Voice process not running; Agent's TTS key invalid (Voice prompts → Preview); firewall blocking 10000–20000/UDP |
| Speaking hands the call to a human | Agent's STT key rejected — `python -m scripts.phone_stt_test --stt <provider>` |
| Keys not detected | Softphone DTMF mode must be RFC 2833 |
| Calls take 10+ s to answer | Voice process still warming up, or `TELEPHONY_VOICE_IDLE_PROCESSES=0` |
| Webhook 401 in backend log | Backend `LIVEKIT_API_KEY/SECRET` don't match `livekit.yaml` |
