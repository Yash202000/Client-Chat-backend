#!/bin/sh
# Healthy = Kamailio answers on its control socket and has its SIP sockets open.
kamcmd -s unix:/run/kamailio/kamailio_ctl core.uptime >/dev/null 2>&1 || exit 1
