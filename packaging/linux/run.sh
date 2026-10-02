#!/usr/bin/env sh
# Uruchamia GUI chd_buddy ze środowiska .venv (patrz install.sh).
set -eu
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "Brak środowiska .venv — uruchom najpierw ./install.sh" >&2
    exit 1
fi

exec .venv/bin/python -m chd_buddy.main "$@"
