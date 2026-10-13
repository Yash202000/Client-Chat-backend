# Contact centre: high availability (no single point of failure)

Goal: losing any one machine or service does not stop the contact centre. New calls keep working. Calls
that were connected through the failed piece drop; that is normal for telephony, and the caller calls
back and gets through.

Tested end to end on one machine with the **HA lab** (`telephony/ha/`) and
`scripts/telephony_ha_test.py`, plus `scripts/sip_registrar_ha_test.py` for the registrars.

## Single node or HA? (chosen per deployment, by settings only)

The same code and images run either way. Local development and small deployments stay single node:
leave the HA settings empty.

| Piece | Single (dev / small deploy) | HA deploy |
|---|---|---|
| Backend `.env` | `LIVEKIT_URL`, `LIVEKIT_PUBLIC_URL`, `REDIS_URL` | add `LIVEKIT_URLS`, `LIVEKIT_PUBLIC_URLS`, `REDIS_SENTINELS` (and empty `REDIS_URL`) |
| SIP registrar | `SIP_PEERS` empty, one address in `LIVEKIT_SIP_ADDRESSES` | `SIP_PEERS` = other registrar(s), unique `SIP_SERVER_ID`, every LiveKit SIP node listed |
| LiveKit / SIP / Egress yaml | `redis: address: …` | `redis: sentinel_…`; SIP / Egress `ws_url` = the host's local HAProxy |
| Compose | `backend/docker-compose.yml` | one stack per host as below (`telephony/ha/` is the one-machine lab) |
| Second dev registrar | not started (default) | `docker compose --profile ha up -d sip-registrar sip-registrar-2` only to test the pair |

Always on, harmless when single: registrations are stored in Postgres (one registrar: phones stay logged in
across restarts; needs `alembic upgrade head`), and with only `LIVEKIT_URL` set the backend uses that node
without health checks.

## Layout

Two hosts (A and B), each running a full "side", plus a small third machine for the third Redis sentinel
(any VM; it only votes).

| Service | Host A | Host B | How it stays up |
|---|---|---|---|
| SIP registrar (Kamailio) | ✓ | ✓ | Registrations live in Postgres (`kamailio.location`), so both registrars see every phone and logins survive restarts. A call to a phone goes via the registrar the phone is on; if that registrar is down, the other one reaches the phone directly. |
| LiveKit server | ✓ | ✓ | One cluster through Redis: a room on either node can be joined and controlled through both. The backend picks a healthy node (`LIVEKIT_URLS`) and sends agents' browsers to it. |
| Local LiveKit address (HAProxy) | ✓ | ✓ | `127.0.0.1:7880`-style address on each host for LiveKit SIP / Egress / voice processes: the host's own node first, the other node at once when it is down. |
| LiveKit SIP | ✓ | ✓ | The registrars spread calls over both (OPTIONS probes, failover on timeout / 5xx). The operator's trunk should also list both IPs. Outbound calls are placed by whichever SIP node is free. |
| LiveKit Egress (recording) | ✓ | ✓ | Recording jobs go to any free Egress instance. |
| Voice process (AI / IVR) | ✓ | ✓ | Workers on both hosts register with the cluster; jobs go to available workers. |
| Redis | master | replica | **Sentinel** (sentinels on A, B and the third machine, quorum 2) promotes the replica in ~5 s. LiveKit, SIP, Egress and the backend all follow the new master by themselves. |
| Backend API | ✓ | ✓ | Stateless behind the web load balancer. Websocket events cross processes through Redis. The ACD dispatcher holds a Redis lock, so only one runs at a time. |
| Postgres | — | — | **Not covered here**: use a managed Postgres or Patroni (primary + standby). Everything above depends on it. |
| MinIO / S3 (recordings) | — | — | **Not covered here**: use S3 or MinIO in distributed mode. |

## Settings

**Backend `.env`** (both hosts):
```
LIVEKIT_URLS=ws://10.0.0.11:7880,ws://10.0.0.12:7880          # the nodes, as the backend reaches them
LIVEKIT_PUBLIC_URLS=wss://lk-a.example.com,wss://lk-b.example.com  # same order, as browsers reach them
REDIS_URL=
REDIS_SENTINELS=10.0.0.11:26379,10.0.0.12:26379,10.0.0.13:26379
REDIS_SENTINEL_MASTER=agentconnect
REDIS_PASSWORD=...            # if Redis has a password (recommended)
```
With only `LIVEKIT_URL` / `LIVEKIT_PUBLIC_URL` / `REDIS_URL` set, everything works as a single node, as before.

**LiveKit server, LiveKit SIP, Egress** (yaml): replace `redis: address:` with
```yaml
redis:
  sentinel_master_name: agentconnect
  sentinel_addresses: [10.0.0.11:26379, 10.0.0.12:26379, 10.0.0.13:26379]
  # password: ...
```
LiveKit SIP and Egress `ws_url` → the host's local HAProxy address (see `ha/lb-a.cfg`), not one node.
The voice process on each host: `LIVEKIT_URL` = that host's local HAProxy address.

**SIP registrars** (`registrar.env`, one per host):
```
SIP_SERVER_ID=1                                 # 2 on host B (unique per registrar)
SIP_PEERS=10.0.0.12:5080                        # the other registrar(s), private addresses
LIVEKIT_SIP_ADDRESSES=10.0.0.11:5060,10.0.0.12:5060
SIP_MAX_EXPIRES=600                             # phones re-register at least every 10 min
KAMAILIO_DB_URL=postgres://sip_registrar:...@db:5432/heygenally
```
Run `alembic upgrade head` (creates schema `kamailio`) and then `readonly-role.sql`. The role reads the logins
view and writes only `kamailio.location`. Allow about 30 connections per registrar.

**Softphones** must find the second registrar when the first is down. Either:
- a DNS name with SRV records `_sip._udp` / `_sip._tcp` pointing at both registrars (PortSIP, Zoiper and most
  desk phones follow SRV), or
- the phone's "backup / failover server" field set to the second registrar.

## What happens when…

| Failure | Effect | Recovery |
|---|---|---|
| Registrar A down | Phones on A can't place calls until they re-register with B (SRV / backup server; at most `SIP_MAX_EXPIRES`). Calls *to* those phones are sent by B directly (works without NAT). Phones on B unaffected. | Start A; nothing to resync. |
| LiveKit SIP node down | Its calls drop. Registrars stop using it within ~5 s (first failed call) or 20 s (probes). New calls go to the other node. | Start it; probes add it back. |
| LiveKit node down | Rooms hosted on it end (their calls drop). Backend, agents, SIP, Egress and voice processes use the other node within ~5 s. | Start it. |
| Redis master down | ~5 s of failed Redis operations (live dashboard events may be missed). Sentinel promotes the replica and every client reconnects. | Start it; it rejoins as a replica. |
| A whole host down | All of the above for that side at once. The other side carries all calls; size each side for the full peak. | Start the host. |

## Running the HA lab (one machine)

From `backend/`:
```bash
docker compose -f telephony/ha/docker-compose.yml up -d    # needs agentconnect-sip-registrar:1.1.0 built
# test API on :8010 with the lab settings (LiveKit webhooks go there):
LIVEKIT_URL=ws://localhost:7960 LIVEKIT_URLS=ws://localhost:7960,ws://localhost:7970 \
LIVEKIT_PUBLIC_URLS=ws://<lan-ip>:7960,ws://<lan-ip>:7970 \
REDIS_URL= REDIS_SENTINELS=127.0.0.1:26390,127.0.0.1:26391,127.0.0.1:26392 REDIS_SENTINEL_MASTER=agentconnect \
  uvicorn app.main:app --port 8010 &
# same variables in this shell, then:
python -m scripts.telephony_ha_test
docker compose -f telephony/ha/docker-compose.yml down
```
Registrar pair on the normal dev stack: `SIP_REGISTRAR_PEERS=<lan-ip>:5082 docker compose --profile ha up -d
sip-registrar sip-registrar-2`, then `python -m scripts.sip_registrar_ha_test`.

## Not covered yet

- Postgres and MinIO high availability (managed services recommended).
- A call already connected through a failed LiveKit / SIP node is not moved to the other node.
- The operator trunk: ask for two destination IPs (both LiveKit SIP nodes) or SRV.
- The web / API load balancer itself (cloud LB, or keepalived + HAProxy pair).
