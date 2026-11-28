#!/bin/sh
set -e

# Migrate ownership of mounted volumes from older root-run installs before
# dropping privileges to the unprivileged stead user.
if [ "$(id -u)" = "0" ]; then
    for dir in /app/context /app/private /app/inbox; do
        if [ -d "$dir" ]; then
            # Only migrate old root-owned entries. Do not follow symlinks or
            # cross into nested mounts.
            find "$dir" -xdev -uid 0 -exec chown -h stead:stead {} +
        fi
    done
    exec setpriv --reuid=stead --regid=stead --init-groups --no-new-privs "$@"
fi

exec "$@"
