#!/bin/sh
set -eu
/usr/local/bin/python -I /opt/rv-retention/verify_bundle.py
exec /usr/local/bin/python -I /opt/rv-retention/watchdog.py
