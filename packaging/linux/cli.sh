#!/usr/bin/env sh
# Uruchamia CLI chd_buddy ze środowiska .venv (patrz install.sh).
#   ./cli.sh --help
#   ./cli.sh audit /sciezka/do/romow
set -eu
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
    echo "Brak środowiska .venv — uruchom najpierw ./install.sh" >&2
    exit 1
fi

exec .venv/bin/python -m chd_buddy.cli "$@"
