# PyInstaller spec for HYDRA-Win: one folder, windowed, UTF-8 mode.
# Build from the repository root:  pyinstaller packaging/hydra-win.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
ASSETS = SRC / "hydra_win" / "assets"

datas = [
    (str(SRC / "hydra_amr" / "data"), "hydra_amr/data"),
    (str(SRC / "hydra_amr" / "LICENSE"), "hydra_amr"),
    (str(SRC / "hydra_amr" / "VENDORED.txt"), "hydra_amr"),
    (str(ASSETS), "hydra_win/assets"),  # logo and window icon
]
datas += collect_data_files("tkinterdnd2")
binaries = collect_dynamic_libs("tkinterdnd2")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["hydra_amr.db.fetch", "tkinterdnd2"],
    excludes=["pandas", "scipy", "matplotlib", "pysam", "IPython", "pytest",
              "hydra_amr.report", "hydra_amr.cli"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [("X utf8", None, "OPTION")],
    exclude_binaries=True,
    name="HYDRA-Win",
    icon=str(ASSETS / "HYDRA-Win.ico"),
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="HYDRA-Win", upx=False)
