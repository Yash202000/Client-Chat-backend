#!/bin/sh
# Builds kamailio.cfg from environment variables, checks it, then runs Kamailio in the foreground.
#
# Required
#   TELEPHONY_SIP_REGISTRAR_ADDRESS  host:port softphones use as SIP server (same value as the backend .env)
#   KAMAILIO_DB_URL                  postgres://user:pass@host:5432/db  (read-only role, see readonly-role.sql)
#                                    — or DATABASE_URL (SQLAlchemy style) as a fallback
# Optional
#   TELEPHONY_SIP_REALM     digest realm, must match the backend (default agentconnect)
#   SIP_LISTEN_IP           local IP to bind (default: the registrar IP if it is on this host, else the first
#                           global IPv4). When it differs from the registrar address that address is advertised
#                           (cloud / NAT: bind the private IP, advertise the public one).
#   LIVEKIT_SIP_ADDRESSES   LiveKit SIP nodes, comma separated host:port (default <listen ip>:5060). Calls are
#                           spread over them, a node that fails is skipped; their calls to phones are trusted.
#                           (LIVEKIT_SIP_ADDRESS, one node, still works)
#   SIP_SERVER_ID           unique number per registrar sharing the database (default 1)
#   SIP_PEERS               the other registrars, comma separated host:port (private addresses). Registrations
#                           are shared through the database; calls to a phone go via the registrar it is on.
#   SIP_MAX_EXPIRES         longest registration in seconds (default 600; shorter = faster failover)
#   SIP_TLS_CERT, SIP_TLS_KEY  PEM files (readable by uid 100) -> also listen for SIP over TLS on SIP_TLS_PORT (5081)
#   SIP_MAX_AUTH_FAILURES   wrong passwords / unknown users from one IP before it is blocked (default 10)
#   SIP_BAN_SECONDS         how long a blocked IP stays blocked (default 900)
#   SIP_FLOOD_REQUESTS      max requests per IP per 2 seconds before it is blocked (default 60)
#   SIP_LOG_LEVEL           Kamailio debug level, 1=errors … 3=debug (default 2)
set -e
RUN_DIR=/run/kamailio
CFG="$RUN_DIR/kamailio.cfg"

REGISTRAR="${TELEPHONY_SIP_REGISTRAR_ADDRESS:?set TELEPHONY_SIP_REGISTRAR_ADDRESS (host:port softphones use)}"
case "$REGISTRAR" in *:*) ;; *) REGISTRAR="$REGISTRAR:5080" ;; esac
ADVERTISE_HOST="${REGISTRAR%:*}"
export SIP_PORT="${REGISTRAR##*:}"
export SIP_REALM="${TELEPHONY_SIP_REALM:-agentconnect}"

LOCAL_IPS="$(ip -4 -o addr show 2>/dev/null | awk '{split($4,a,"/"); print a[1]}')"
if [ -z "$SIP_LISTEN_IP" ]; then
  if echo "$LOCAL_IPS" | grep -qx "$ADVERTISE_HOST"; then
    SIP_LISTEN_IP="$ADVERTISE_HOST"
  else
    SIP_LISTEN_IP="$(ip -4 -o addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}')"
  fi
fi
[ -n "$SIP_LISTEN_IP" ] || { echo "kamailio: cannot work out SIP_LISTEN_IP — set it" >&2; exit 1; }
export SIP_LISTEN_IP
export SIP_TLS_PORT="${SIP_TLS_PORT:-5081}"
export SIP_ADVERTISE="" SIP_ADVERTISE_TLS=""
if [ "$ADVERTISE_HOST" != "$SIP_LISTEN_IP" ]; then
  SIP_ADVERTISE=" advertise ${ADVERTISE_HOST}:${SIP_PORT}"
  SIP_ADVERTISE_TLS=" advertise ${ADVERTISE_HOST}:${SIP_TLS_PORT}"
fi

# host:port -> ip:port (Kamailio compares source addresses, so names, e.g. compose services, are resolved here)
resolve() {
  hp="$1"; default_port="$2"
  case "$hp" in *:*) ;; *) hp="$hp:$default_port" ;; esac
  h="${hp%:*}"; p="${hp##*:}"
  if ! echo "$h" | grep -Eq '^[0-9.]+$'; then
    h="$(getent ahostsv4 "$h" | awk '{print $1; exit}')"
    [ -n "$h" ] || { echo "kamailio: cannot resolve '${hp%:*}'" >&2; exit 1; }
  fi
  echo "$h:$p"
}

# LiveKit SIP nodes (comma separated); calls are spread over them and fail over between them
LK_LIST="${LIVEKIT_SIP_ADDRESSES:-${LIVEKIT_SIP_ADDRESS:-${LIVEKIT_SIP_IP:-$SIP_LISTEN_IP}:${LIVEKIT_SIP_PORT:-5060}}}"
: > "$RUN_DIR/dispatcher.list"
export LIVEKIT_SIP_FIRST=""
for a in $(echo "$LK_LIST" | tr ',' ' '); do
  hp="$(resolve "$a" 5060)"; [ -n "$hp" ] || exit 1
  [ -n "$LIVEKIT_SIP_FIRST" ] || LIVEKIT_SIP_FIRST="$hp"
  echo "1 sip:$hp;transport=udp 0 0" >> "$RUN_DIR/dispatcher.list"
done

# other registrars sharing the same database (comma separated host:port, this one may be listed too)
export SIP_SERVER_ID="${SIP_SERVER_ID:-1}"
export SIP_PEER_LIST="" SIP_PEER_COUNT=0
for a in $(echo "${SIP_PEERS:-}" | tr ',' ' '); do
  hp="$(resolve "$a" "$SIP_PORT")"; [ -n "$hp" ] || exit 1
  [ "$hp" = "$SIP_LISTEN_IP:$SIP_PORT" ] && continue
  SIP_PEER_LIST="${SIP_PEER_LIST:+$SIP_PEER_LIST,}$hp"
  SIP_PEER_COUNT=$((SIP_PEER_COUNT + 1))
  echo "2 sip:$hp;transport=udp 0 0" >> "$RUN_DIR/dispatcher.list"
done
export SIP_MAX_EXPIRES="${SIP_MAX_EXPIRES:-600}"

if [ -n "$KAMAILIO_DB_URL" ]; then
  DB_URL="$KAMAILIO_DB_URL"
else
  DB_URL="${DATABASE_URL:?set KAMAILIO_DB_URL (or DATABASE_URL)}"
fi
# SQLAlchemy style (postgresql+psycopg2://…) -> Kamailio style (postgres://…)
export KAMAILIO_DB_URL="$(echo "$DB_URL" | sed -E 's#^postgres(ql)?(\+[a-z0-9]+)?://#postgres://#')"

export SIP_MAX_AUTH_FAILURES="${SIP_MAX_AUTH_FAILURES:-10}"
export SIP_BAN_SECONDS="${SIP_BAN_SECONDS:-900}"
export SIP_FLOOD_REQUESTS="${SIP_FLOOD_REQUESTS:-60}"
export SIP_LOG_LEVEL="${SIP_LOG_LEVEL:-2}"
export RUN_DIR

DEFINES=""
if [ -n "$SIP_TLS_CERT" ] || [ -n "$SIP_TLS_KEY" ]; then
  for f in "$SIP_TLS_CERT" "$SIP_TLS_KEY"; do
    [ -r "$f" ] || { echo "kamailio: TLS file '$f' missing or not readable by uid $(id -u)" >&2; exit 1; }
  done
  cat > "$RUN_DIR/tls.cfg" <<TLS
[server:default]
method = TLSv1.2+
verify_certificate = no
require_certificate = no
certificate = $SIP_TLS_CERT
private_key = $SIP_TLS_KEY

[client:default]
method = TLSv1.2+
verify_certificate = no
require_certificate = no
TLS
  DEFINES="-A WITH_TLS"
fi

envsubst '${SIP_LISTEN_IP} ${SIP_ADVERTISE} ${SIP_ADVERTISE_TLS} ${SIP_PORT} ${SIP_TLS_PORT} ${SIP_REALM} ${LIVEKIT_SIP_FIRST} ${SIP_SERVER_ID} ${SIP_PEER_LIST} ${SIP_PEER_COUNT} ${SIP_MAX_EXPIRES} ${KAMAILIO_DB_URL} ${SIP_MAX_AUTH_FAILURES} ${SIP_BAN_SECONDS} ${SIP_FLOOD_REQUESTS} ${SIP_LOG_LEVEL} ${RUN_DIR}' \
  < /etc/kamailio/kamailio.cfg.tpl > "$CFG"
chmod 600 "$CFG"

echo "kamailio: listening ${SIP_LISTEN_IP}:${SIP_PORT} udp+tcp${DEFINES:+ + tls :${SIP_TLS_PORT}}${SIP_ADVERTISE:+ (${SIP_ADVERTISE# })}, realm ${SIP_REALM}, server id ${SIP_SERVER_ID}"
echo "kamailio: LiveKit SIP nodes: $(grep '^1 ' "$RUN_DIR/dispatcher.list" | awk '{print $2}' | tr '\n' ' ')"
echo "kamailio: peer registrars: ${SIP_PEER_LIST:-none}"
kamailio -c $DEFINES -f "$CFG"
exec kamailio -DD -E $DEFINES -P "$RUN_DIR/kamailio.pid" -f "$CFG"
