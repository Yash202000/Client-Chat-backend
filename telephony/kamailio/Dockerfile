# AgentConnect SIP registrar: softphones (PortSIP, Zoiper, MicroSIP, …) log in with HeyGenAlly users'
# SIP accounts and their calls are relayed to LiveKit SIP. Signalling only — audio goes phone <-> LiveKit SIP.
# Debian's maintained Kamailio packages (the official kamailio images are stale).
#
#   build:   ./build.sh [version]            (or: docker build -t agentconnect-sip-registrar:<v> .)
#   run:     see docker-compose.deploy.yml and README.md (all settings come from environment variables)
FROM debian:bookworm-slim

ARG KAMAILIO_VERSION=5.6.3-2
ARG VERSION=dev
LABEL org.opencontainers.image.title="agentconnect-sip-registrar" \
      org.opencontainers.image.description="SIP registrar/proxy for AgentConnect softphones (Kamailio) in front of LiveKit SIP" \
      org.opencontainers.image.version="${VERSION}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      kamailio=${KAMAILIO_VERSION} kamailio-postgres-modules=${KAMAILIO_VERSION} kamailio-tls-modules=${KAMAILIO_VERSION} \
      gettext-base iproute2 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /run/kamailio && chown kamailio:kamailio /run/kamailio

COPY kamailio.cfg.tpl /etc/kamailio/kamailio.cfg.tpl
COPY entrypoint.sh /entrypoint.sh
COPY healthcheck.sh /healthcheck.sh
RUN chmod 0755 /entrypoint.sh /healthcheck.sh

# unprivileged: ports above 1024 only (defaults 5080 udp/tcp, 5081 tls)
USER kamailio
EXPOSE 5080/udp 5080/tcp 5081/tcp
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["/healthcheck.sh"]
ENTRYPOINT ["/entrypoint.sh"]
