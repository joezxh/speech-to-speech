#!/bin/sh
set -eu
mkdir -p /var/log/supervisor /run/s2s-console /app/data
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
