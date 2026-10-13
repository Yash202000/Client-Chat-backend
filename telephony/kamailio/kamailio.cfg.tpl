#!KAMAILIO
# AgentConnect SIP registrar / proxy (generated from kamailio.cfg.tpl by entrypoint.sh)
#
#  softphone --REGISTER--> here (digest auth against HeyGenAlly users: view kamailio_subscriber)
#  softphone --INVITE 980--> here --> LiveKit SIP (caller = the softphone's SIP username)
#  softphone --INVITE <user>--> here --> that registered softphone
#  LiveKit SIP --INVITE <user>--> here --> that registered softphone (callbacks / outbound tests)
#
# High availability:
#  - registrations live in the database (kamailio.location, usrloc DB-only mode), so they survive a
#    restart and every registrar sees every phone;
#  - a phone is always reached through the registrar it registered with (its NAT pinhole / TCP
#    connection is with that one): other registrars ("peers", SIP_PEERS) forward the call there, and
#    send it directly only if that registrar is down;
#  - calls to contact-centre numbers are spread over the LiveKit SIP nodes (LIVEKIT_SIP_ADDRESSES),
#    which are probed with OPTIONS; a node that fails is skipped and the call goes to the next one.
#
# Signalling only: audio flows directly between the softphone and LiveKit SIP (RTP 10000-20000/udp).

debug=${SIP_LOG_LEVEL}
log_stderror=yes
log_facility=LOG_LOCAL0
children=4
tcp_connection_lifetime=3605
server_id=${SIP_SERVER_ID}
server_header="Server: AgentConnect SIP"
user_agent_header="User-Agent: AgentConnect SIP"

listen=udp:${SIP_LISTEN_IP}:${SIP_PORT}${SIP_ADVERTISE}
listen=tcp:${SIP_LISTEN_IP}:${SIP_PORT}${SIP_ADVERTISE}
#!ifdef WITH_TLS
enable_tls=yes
listen=tls:${SIP_LISTEN_IP}:${SIP_TLS_PORT}${SIP_ADVERTISE_TLS}
loadmodule "tls.so"
modparam("tls", "config", "${RUN_DIR}/tls.cfg")
#!endif

loadmodule "kex.so"
loadmodule "corex.so"
loadmodule "tm.so"
loadmodule "tmx.so"
loadmodule "sl.so"
loadmodule "rr.so"
loadmodule "pv.so"
loadmodule "maxfwd.so"
loadmodule "usrloc.so"
loadmodule "registrar.so"
loadmodule "textops.so"
loadmodule "siputils.so"
loadmodule "xlog.so"
loadmodule "sanity.so"
loadmodule "db_postgres.so"
loadmodule "auth.so"
loadmodule "auth_db.so"
loadmodule "nathelper.so"
loadmodule "ctl.so"
loadmodule "htable.so"
loadmodule "pike.so"
loadmodule "sqlops.so"
loadmodule "dispatcher.so"

# control socket for kamcmd / the container health check
modparam("ctl", "binrpc", "unix:${RUN_DIR}/kamailio_ctl")

# protection when exposed to the internet: blocked IPs, wrong-password counters, request floods
modparam("htable", "htable", "ipban=>size=10;autoexpire=${SIP_BAN_SECONDS};")
modparam("htable", "htable", "authfail=>size=10;autoexpire=${SIP_BAN_SECONDS};")
modparam("pike", "sampling_time_unit", 2)
modparam("pike", "reqs_density_per_unit", ${SIP_FLOOD_REQUESTS})
modparam("pike", "remove_latency", 4)

# registrations in the database (schema "kamailio", table location): shared by all registrars,
# kept across restarts. Each registrar keeps alive (NAT pings) only the phones registered with it.
modparam("usrloc", "db_url", "${KAMAILIO_DB_URL}")
modparam("usrloc", "db_mode", 3)
modparam("usrloc", "server_id_filter", 1)
modparam("usrloc", "nat_bflag", 6)
modparam("usrloc", "timer_interval", 60)
modparam("registrar", "max_expires", ${SIP_MAX_EXPIRES})
modparam("registrar", "default_expires", ${SIP_MAX_EXPIRES})
modparam("registrar", "received_avp", "$avp(RECEIVED)")
modparam("nathelper", "received_avp", "$avp(RECEIVED)")
modparam("nathelper", "natping_interval", 30)
modparam("nathelper", "ping_nated_only", 1)
modparam("nathelper", "sipping_bflag", 7)
modparam("nathelper", "sipping_from", "sip:keepalive@${SIP_LISTEN_IP}")
modparam("sqlops", "sqlcon", "ca=>${KAMAILIO_DB_URL}")

# set 1 = LiveKit SIP nodes, set 2 = peer registrars (both probed with OPTIONS)
modparam("dispatcher", "list_file", "${RUN_DIR}/dispatcher.list")
modparam("dispatcher", "flags", 2)
modparam("dispatcher", "ds_ping_interval", 10)
modparam("dispatcher", "ds_probing_mode", 1)
modparam("dispatcher", "ds_probing_threshold", 2)
modparam("dispatcher", "ds_inactive_threshold", 1)
modparam("dispatcher", "ds_ping_from", "sip:keepalive@${SIP_LISTEN_IP}")
modparam("dispatcher", "ds_ping_reply_codes", "class=2;class=4")

# accounts = active HeyGenAlly users with an enabled SIP account (sip_accounts table)
modparam("auth_db", "db_url", "${KAMAILIO_DB_URL}")
modparam("auth_db", "calculate_ha1", 0)
modparam("auth_db", "password_column", "ha1")
modparam("auth_db", "user_column", "username")
modparam("auth_db", "use_domain", 0)
modparam("auth_db", "load_credentials", "")

modparam("rr", "enable_full_lr", 1)
modparam("rr", "append_fromtag", 0)
modparam("tm", "fr_timer", 5000)
modparam("tm", "fr_inv_timer", 60000)

request_route {
    route(SECURITY);
    if (!mf_process_maxfwd_header("10")) {
        sl_send_reply("483", "Too Many Hops");
        exit;
    }
    if (!sanity_check("17895", "7")) {
        exit;
    }
    force_rport();
    if (nat_uac_test("19") && !ds_is_from_list("2")) {
        if (is_method("REGISTER")) {
            fix_nated_register();
        } else {
            fix_nated_contact();
        }
        setflag(5);
    }

    if (is_method("CANCEL")) {
        if (t_check_trans()) {
            route(RELAY);
        }
        exit;
    }
    if (has_totag()) {
        route(WITHINDLG);
        exit;
    }
    t_check_trans();

    if (is_method("OPTIONS") && uri == myself && $rU == $null) {
        sl_send_reply("200", "Keepalive");
        exit;
    }
    if (is_method("REGISTER")) {
        route(REGISTRAR);
        exit;
    }

    remove_hf("Route");
    record_route();

    # a peer registrar forwards calls for phones registered here: deliver them
    if (ds_is_from_list("2")) {
        route(TO_PHONE);
        exit;
    }
    # calls from LiveKit SIP to a softphone (callbacks, outbound) are trusted
    if (ds_is_from_list("1")) {
        route(TO_PHONE);
        exit;
    }

    # everything else must come from a logged-in system user, calling as themselves
    route(AUTH);

    if (registered("location")) {
        route(TO_PHONE);   # another softphone
        exit;
    }
    route(TO_LIVEKIT);     # a contact-centre number (e.g. 980)
}

route[SECURITY] {
    if (ds_is_from_list("1") || ds_is_from_list("2")) {
        return;
    }
    if ($sht(ipban=>$si) != $null) {
        exit;   # blocked: drop silently
    }
    if ($ua =~ "friendly-scanner|sipvicious|sipcli|sip-scan|VaxSIPUserAgent|pplsip|iWar|sundayddr") {
        exit;
    }
    if (!pike_check_req()) {
        $sht(ipban=>$si) = 1;
        xlog("L_ALERT", "SECURITY: request flood from $si:$sp - blocked for ${SIP_BAN_SECONDS}s\n");
        exit;
    }
}

# digest auth against active HeyGenAlly users' SIP accounts; repeated failures block the IP
route[AUTH] {
    auth_check("${SIP_REALM}", "kamailio_subscriber", "1");
    $var(rc) = $rc;
    if ($var(rc) == -2 || $var(rc) == -3) {
        xlog("L_WARN", "SECURITY: failed login for '$au' from $si:$sp\n");
        if ($sht(authfail=>$si) == $null) {
            $sht(authfail=>$si) = 1;
        } else {
            $sht(authfail=>$si) = $sht(authfail=>$si) + 1;
        }
        if ($sht(authfail=>$si) >= ${SIP_MAX_AUTH_FAILURES}) {
            $sht(ipban=>$si) = 1;
            xlog("L_ALERT", "SECURITY: ${SIP_MAX_AUTH_FAILURES} failed logins from $si - blocked for ${SIP_BAN_SECONDS}s\n");
            exit;
        }
    }
    if ($var(rc) < 0) {
        auth_challenge("${SIP_REALM}", "0");
        exit;
    }
    $sht(authfail=>$si) = $null;
    consume_credentials();
}

route[REGISTRAR] {
    route(AUTH);
    if (isflagset(5)) {
        setbflag(6);
        setbflag(7);
    }
    if (!save("location")) {
        sl_reply_error();
    }
    xlog("L_INFO", "registered $tU from $si:$sp\n");
    exit;
}

route[TO_PHONE] {
    # which registrar does the phone talk to? (the socket it registered on)
    $var(owner) = "";
    if (sql_xquery("ca", "SELECT socket FROM location WHERE username = '$(rU{s.escape.common})' ORDER BY last_modified DESC LIMIT 1", "own") == 1) {
        $var(owner) = $xavp(own=>socket);
    }
    if ($var(owner) != "" && $var(owner) != $null && !ds_is_from_list("2")) {
        $var(o_proto) = $(var(owner){s.select,0,:});
        $var(o_ip) = $(var(owner){s.select,1,:});
        $var(o_port) = $(var(owner){s.select,2,:}{s.int});
        $var(local) = 0;
        if ($var(o_ip) == "${SIP_LISTEN_IP}" && ($var(o_port) == ${SIP_PORT} || $var(o_port) == ${SIP_TLS_PORT})) {
            $var(local) = 1;
        }
        if ($var(local) == 0) {
            # find the peer: same address, or (phone on TLS) the peer on that IP
            $var(peers) = "${SIP_PEER_LIST}";
            $var(i) = 0;
            $var(target) = "";
            while ($var(i) < ${SIP_PEER_COUNT} && $var(target) == "") {
                $var(p) = $(var(peers){s.select,$var(i),,});
                if ($var(p) == $_s($var(o_ip):$var(o_port))
                        || ($var(o_proto) == "tls" && $(var(p){s.select,0,:}) == $var(o_ip))) {
                    $var(target) = $var(p);
                }
                $var(i) = $var(i) + 1;
            }
            if ($var(target) != "") {
                xlog("L_INFO", "call to $rU: phone is on registrar $var(target), forwarding\n");
                $avp(peer) = $var(target);
                $du = "sip:" + $var(target);
                t_on_failure("PEER_DOWN");
                route(RELAY);
                exit;
            }
        }
    }
    if (!lookup("location")) {
        t_newtran();
        t_reply("404", "Not Registered");
        exit;
    }
    route(RELAY);
}

route[TO_LIVEKIT] {
    # spread over the LiveKit SIP nodes (round robin over the ones answering OPTIONS)
    if (!ds_select_dst("1", "4")) {
        $du = "sip:${LIVEKIT_SIP_FIRST};transport=udp";   # all probes failing: try the first node anyway
    }
    xlog("L_INFO", "call from $fU to $rU -> LiveKit SIP $du\n");
    t_on_failure("LIVEKIT_FAILOVER");
    route(RELAY);
}

route[WITHINDLG] {
    if (loose_route()) {
        route(RELAY);
        exit;
    }
    if (is_method("ACK")) {
        if (t_check_trans()) {
            route(RELAY);
        }
        exit;
    }
    sl_send_reply("404", "Not Here");
    exit;
}

route[RELAY] {
    if (is_method("INVITE")) {
        t_on_reply("NATREPLY");
    }
    if (!t_relay()) {
        sl_reply_error();
    }
    exit;
}

onreply_route[NATREPLY] {
    if (nat_uac_test("1") && !ds_is_from_list("1") && !ds_is_from_list("2")) {
        fix_nated_contact();
    }
}

# the LiveKit SIP node didn't answer or is overloaded: next node
failure_route[LIVEKIT_FAILOVER] {
    if (t_is_canceled()) {
        exit;
    }
    if (t_check_status("408|500|503") || (t_branch_timeout() && !t_branch_replied())) {
        ds_mark_dst("ip");
        if (ds_next_dst()) {
            xlog("L_WARN", "LiveKit SIP node failed for call to $rU, trying $du\n");
            t_on_failure("LIVEKIT_FAILOVER");
            t_relay();
        }
    }
}

# the registrar the phone is on is down: reach the phone directly (works when there is no NAT in between)
failure_route[PEER_DOWN] {
    if (t_is_canceled()) {
        exit;
    }
    if (t_check_status("408|503") || (t_branch_timeout() && !t_branch_replied())) {
        xlog("L_WARN", "registrar $avp(peer) is down: calling $rU's phone directly\n");
        $du = $null;
        if (lookup("location")) {
            t_on_reply("NATREPLY");
            t_relay();
        }
    }
}
