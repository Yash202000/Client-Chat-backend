"""SIP registrar high availability: registrations stored in the database (schema "kamailio")

Kamailio's usrloc (DB-only mode) keeps every softphone registration in kamailio.location, so they
survive a registrar restart and all registrars share them. Tables are Kamailio 5.6's own schema
(usrloc-create.sql, standard-create.sql); the registrar finds them through its role's search_path
(see telephony/kamailio/readonly-role.sql).

Revision ID: j0k1a2m3l4o5
Revises: i9w0a1i2t3r4
Create Date: 2026-10-14 00:00:02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'j0k1a2m3l4o5'
down_revision: Union[str, Sequence[str], None] = 'i9w0a1i2t3r4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = """
CREATE SCHEMA IF NOT EXISTS kamailio;

CREATE TABLE IF NOT EXISTS kamailio.version (
    id SERIAL PRIMARY KEY NOT NULL,
    table_name VARCHAR(32) NOT NULL,
    table_version INTEGER DEFAULT 0 NOT NULL,
    CONSTRAINT version_table_name_idx UNIQUE (table_name)
);

CREATE TABLE IF NOT EXISTS kamailio.location (
    id SERIAL PRIMARY KEY NOT NULL,
    ruid VARCHAR(64) DEFAULT '' NOT NULL,
    username VARCHAR(64) DEFAULT '' NOT NULL,
    domain VARCHAR(64) DEFAULT NULL,
    contact VARCHAR(512) DEFAULT '' NOT NULL,
    received VARCHAR(128) DEFAULT NULL,
    path VARCHAR(512) DEFAULT NULL,
    expires TIMESTAMP WITHOUT TIME ZONE DEFAULT '2030-05-28 21:32:15' NOT NULL,
    q REAL DEFAULT 1.0 NOT NULL,
    callid VARCHAR(255) DEFAULT 'Default-Call-ID' NOT NULL,
    cseq INTEGER DEFAULT 1 NOT NULL,
    last_modified TIMESTAMP WITHOUT TIME ZONE DEFAULT '2000-01-01 00:00:01' NOT NULL,
    flags INTEGER DEFAULT 0 NOT NULL,
    cflags INTEGER DEFAULT 0 NOT NULL,
    user_agent VARCHAR(255) DEFAULT '' NOT NULL,
    socket VARCHAR(64) DEFAULT NULL,
    methods INTEGER DEFAULT NULL,
    instance VARCHAR(255) DEFAULT NULL,
    reg_id INTEGER DEFAULT 0 NOT NULL,
    server_id INTEGER DEFAULT 0 NOT NULL,
    connection_id INTEGER DEFAULT 0 NOT NULL,
    keepalive INTEGER DEFAULT 0 NOT NULL,
    partition INTEGER DEFAULT 0 NOT NULL,
    CONSTRAINT location_ruid_idx UNIQUE (ruid)
);
CREATE INDEX IF NOT EXISTS location_account_contact_idx ON kamailio.location (username, domain, contact);
CREATE INDEX IF NOT EXISTS location_expires_idx ON kamailio.location (expires);
CREATE INDEX IF NOT EXISTS location_tcpcon_idx ON kamailio.location (connection_id);
CREATE INDEX IF NOT EXISTS location_connection_idx ON kamailio.location (server_id, connection_id);

INSERT INTO kamailio.version (table_name, table_version) VALUES ('version', 1), ('location', 9)
ON CONFLICT (table_name) DO NOTHING;
"""

# the registrar's login (created by readonly-role.sql) may already exist: give it the new tables
GRANTS = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sip_registrar') THEN
    GRANT USAGE ON SCHEMA kamailio TO sip_registrar;
    GRANT SELECT ON kamailio.version TO sip_registrar;
    GRANT SELECT, INSERT, UPDATE, DELETE ON kamailio.location TO sip_registrar;
    GRANT USAGE, SELECT ON SEQUENCE kamailio.location_id_seq TO sip_registrar;
    ALTER ROLE sip_registrar SET search_path = kamailio, public;
  END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(GRANTS)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS kamailio CASCADE")
