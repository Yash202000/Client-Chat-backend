-- Database login for the SIP registrar, least privilege:
--   * read   public.kamailio_subscriber  (username + SIP digest hash of active users with an enabled SIP account)
--   * read   kamailio.version
--   * write  kamailio.location           (softphone registrations, shared by all registrars)
-- Nothing else in the application database. Run once as the DB owner, after the migrations:
--   psql "$DATABASE_URL_PLAIN" -v pw="'choose-a-strong-password'" -f readonly-role.sql
-- then give every registrar  KAMAILIO_DB_URL=postgres://sip_registrar:<password>@<db-host>:5432/<db>
\set ON_ERROR_STOP on
SELECT 'CREATE ROLE sip_registrar LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sip_registrar')\gexec
-- each registrar keeps ~15-30 connections (one per process and module): allow for every registrar
ALTER ROLE sip_registrar WITH LOGIN PASSWORD :pw CONNECTION LIMIT 100;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM sip_registrar;
GRANT CONNECT ON DATABASE :"DBNAME" TO sip_registrar;
GRANT USAGE ON SCHEMA public TO sip_registrar;
GRANT SELECT ON public.kamailio_subscriber TO sip_registrar;
GRANT USAGE ON SCHEMA kamailio TO sip_registrar;
GRANT SELECT ON kamailio.version TO sip_registrar;
GRANT SELECT, INSERT, UPDATE, DELETE ON kamailio.location TO sip_registrar;
GRANT USAGE, SELECT ON SEQUENCE kamailio.location_id_seq TO sip_registrar;
-- Kamailio uses unqualified table names
ALTER ROLE sip_registrar SET search_path = kamailio, public;
