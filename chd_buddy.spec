# -*- mode: python ; coding: utf-8 -*-
# Budowa przenośnego .exe:  pyinstaller --noconfirm chd_buddy.spec
# Ustawienia zapisywane są OBOK exe (portable), nie w AppData.

block_cipher = None

# Wszystkie submoduły pakietu jawnie — `main.py` importuje UI LENIWIE (w funkcji),
# więc analiza statyczna PyInstallera bywała gubiona przy zaśmieconym cache `build/`
# (efekt: niekompletny exe „No module named chd_buddy.ui.suite_window"). Jawna
# lista jest odporna na to niezależnie od stanu cache.
from PyInstaller.utils.hooks import collect_submodules
_hidden = collect_submodules("chd_buddy")

a = Analysis(
    ["chd_buddy/main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        # ("resources", "resources"),  # jeśli dodasz ikony/style
    ],
    hiddenimports=_hidden,
    hookspath=[],
    excludes=["tkinter", "test", "unittest"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ROM Helper",
    debug=False,
    strip=False,
    upx=True,
    console=False,          # GUI bez okna konsoli
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
)
