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
    # The clinical species Mash sketch and the table of genomes behind it;
    # databases.install_clinical_sketch() copies the sketch into db\sketch\species.
    (str(SRC / "hydra_win" / "data"), "hydra_win/data"),
]
datas += collect_data_files("tkinterdnd2")
binaries = collect_dynamic_libs("tkinterdnd2")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    # The organism typing modules are found at run time by name (the registry
    # keeps an explicit list precisely because a frozen build cannot walk the
    # package directory), so PyInstaller cannot see the imports and each one
    # has to be named here.
    hiddenimports=["hydra_amr.db.fetch", "tkinterdnd2", "truststore"] + [
        f"hydra_amr.typing.organisms.{name}" for name in (
            "registry", "base", "strep_common", "_hinf_nmen_common",
            "ecoli", "hinfluenzae", "nmeningitidis", "sagalactiae",
            "salmonella", "saureus", "spneumoniae", "spyogenes")],
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
