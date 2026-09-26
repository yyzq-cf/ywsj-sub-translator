#!/bin/sh
# Fix /data permissions if running as root (bind mount may be owned by host root)
if [ "$(id -u)" = '0' ]; then
    chown -R appuser:appgroup /data
    exec gosu appuser "$@"
fi
exec "$@"
