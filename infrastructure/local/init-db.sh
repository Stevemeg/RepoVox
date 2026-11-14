#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname postgres \
  -v migrator="$MIGRATION_PASSWORD" -v app="$APP_DATABASE_PASSWORD" -v worker="$WORKER_DATABASE_PASSWORD" \
  -v media_migrator="$MEDIA_MIGRATION_PASSWORD" -v media_app="$MEDIA_APP_PASSWORD" \
  -v media_worker="$MEDIA_WORKER_PASSWORD" <<'SQL'
CREATE ROLE rv_executor NOLOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE rv_migrator LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS PASSWORD :'migrator';
CREATE ROLE rv_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'app';
CREATE ROLE rv_worker LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'worker';
-- Non-login capability groups only. No runtime service or credential is provisioned.
CREATE ROLE rv_pilot_controller NOLOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE rv_pilot_executor NOLOGIN NOSUPERUSER NOBYPASSRLS;
GRANT rv_executor TO rv_migrator;
CREATE DATABASE repovox OWNER rv_migrator;
REVOKE ALL ON DATABASE repovox FROM PUBLIC;
GRANT CONNECT ON DATABASE repovox TO rv_migrator,rv_app,rv_worker;
GRANT CONNECT ON DATABASE repovox TO rv_pilot_controller,rv_pilot_executor;
-- Product media: a separate database with its own roles. These roles cannot connect
-- to the core database, and core roles cannot connect to the media database.
CREATE ROLE rvm_executor NOLOGIN NOSUPERUSER NOBYPASSRLS;
CREATE ROLE rvm_migrator LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS PASSWORD :'media_migrator';
CREATE ROLE rvm_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'media_app';
CREATE ROLE rvm_worker LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD :'media_worker';
GRANT rvm_executor TO rvm_migrator;
CREATE DATABASE repovox_media OWNER rvm_migrator;
REVOKE ALL ON DATABASE repovox_media FROM PUBLIC;
GRANT CONNECT ON DATABASE repovox_media TO rvm_migrator,rvm_app,rvm_worker;
SQL
