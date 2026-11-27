#!/usr/bin/env sh
# Instalacja chd_buddy na Linuksie: venv + zależności Pythona.
# Nie kompiluje binarki — stawia środowisko obok źródeł, w katalogu .venv.
#
#   ./install.sh              # venv + zależności
#   ./install.sh --desktop    # dodatkowo wpis w menu aplikacji
#   ./install.sh --check      # tylko raport o zależnościach systemowych
set -eu

cd "$(dirname "$0")"

RED=''; YEL=''; GRN=''; DIM=''; OFF=''
if [ -t 1 ]; then
    RED=$(printf '\033[31m'); YEL=$(printf '\033[33m')
    GRN=$(printf '\033[32m'); DIM=$(printf '\033[2m'); OFF=$(printf '\033[0m')
fi
ok()   { printf '%s  OK  %s %s\n' "$GRN" "$OFF" "$1"; }
warn() { printf '%s BRAK %s %s\n' "$YEL" "$OFF" "$1"; }
die()  { printf '%s BŁĄD %s %s\n' "$RED" "$OFF" "$1" >&2; exit 1; }

DO_DESKTOP=0
CHECK_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --desktop) DO_DESKTOP=1 ;;
        --check)   CHECK_ONLY=1 ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) die "nieznany argument: $arg (użyj --help)" ;;
    esac
done

# --- 1. Python >= 3.11 ------------------------------------------------------

find_python() {
    for cand in python3.14 python3.13 python3.12 python3.11 python3 python; do
        command -v "$cand" >/dev/null 2>&1 || continue
        if "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
           >/dev/null 2>&1; then
            printf '%s' "$cand"
            return 0
        fi
    done
    return 1
}

PY=$(find_python) || die "potrzebny Python 3.11+ (znaleziono: $(python3 -V 2>&1 || echo 'brak'))"
ok "Python: $($PY -V) ($(command -v "$PY"))"

# --- 2. Zależności systemowe (informacyjnie) --------------------------------

MISSING=''
note_missing() { MISSING="$MISSING $1"; }

if command -v chdman >/dev/null 2>&1; then
    ok "chdman: $(command -v chdman)"
else
    warn "chdman — bez niego nie ma konwersji ani audytu CHD (pakiet mame-tools)"
    note_missing mame-tools
fi

if command -v 7z >/dev/null 2>&1 || command -v 7zz >/dev/null 2>&1 \
   || command -v 7za >/dev/null 2>&1; then
    ok "7-Zip: $(command -v 7z || command -v 7zz || command -v 7za)"
else
    warn "7z — potrzebny tylko do aktualizacji emulatorów z archiwów .7z"
    note_missing p7zip
fi

if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    ok "sesja graficzna wykryta"
else
    warn "brak DISPLAY/WAYLAND_DISPLAY — GUI ruszy dopiero w sesji graficznej"
fi

if [ -n "$MISSING" ]; then
    printf '\n%sBrakujące pakiety systemowe:%s%s\n' "$DIM" "$MISSING" "$OFF"
    printf '%sInstalacja — patrz DEPS.md (apt / dnf / pacman / zypper).%s\n' \
        "$DIM" "$OFF"
fi

[ "$CHECK_ONLY" -eq 1 ] && exit 0

# --- 3. venv ----------------------------------------------------------------

if ! "$PY" -c 'import venv' >/dev/null 2>&1; then
    die "brak modułu venv — doinstaluj pakiet python3-venv (Debian/Ubuntu) \
albo python3-libs (Fedora)"
fi

if [ ! -x .venv/bin/python ]; then
    printf '\nTworzę środowisko w .venv …\n'
    "$PY" -m venv .venv || die "nie udało się utworzyć .venv"
else
    printf '\nŚrodowisko .venv już istnieje — aktualizuję zależności.\n'
fi

.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements-linux.txt \
    || die "instalacja zależności nie powiodła się (patrz komunikat pipa wyżej)"

# Import PySide6 potrafi paść na braku bibliotek systemowych (libEGL, xcb) —
# lepiej dowiedzieć się teraz niż przy pierwszym uruchomieniu GUI.
if ! .venv/bin/python -c 'import PySide6.QtWidgets' >/dev/null 2>&1; then
    warn "PySide6 zainstalowane, ale nie daje się zaimportować"
    printf '%s  Zwykle brakuje bibliotek systemowych Qt — patrz DEPS.md.%s\n' \
        "$DIM" "$OFF"
    printf '%s  Szczegóły: .venv/bin/python -c "import PySide6.QtWidgets"%s\n' \
        "$DIM" "$OFF"
else
    ok "PySide6 działa"
fi

# --- 4. Wpis w menu aplikacji (opcjonalnie) ---------------------------------

if [ "$DO_DESKTOP" -eq 1 ]; then
    APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$APPS"
    HERE=$(pwd)
    ICON=""
    [ -f assets/chd_buddy.png ] && ICON="Icon=$HERE/assets/chd_buddy.png"
    cat > "$APPS/chd-buddy.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=chd_buddy
Comment=Audyt, konwersja i naprawa plików CHD
Exec="$HERE/run.sh"
Path=$HERE
Terminal=false
Categories=Game;Utility;
$ICON
EOF
    chmod 755 "$APPS/chd-buddy.desktop"
    ok "wpis w menu: $APPS/chd-buddy.desktop"
fi

printf '\n%sGotowe.%s  GUI: ./run.sh    CLI: ./cli.sh --help\n' "$GRN" "$OFF"
