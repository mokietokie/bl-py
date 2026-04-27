# packaging/bl_tracker.spec
# Build:  pyinstaller packaging/bl_tracker.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

datas = []
datas += collect_data_files("playwright")          # Playwright JS bridge
datas += collect_data_files("reverse_geocoder")    # offline city/country DB (.csv)
datas += [("../src/bl_tracker/web", "bl_tracker/web"),
          ("../src/bl_tracker/db/schema.sql", "bl_tracker/db")]

hidden = []
hidden += collect_submodules("uvicorn")
hidden += collect_submodules("fastapi")
hidden += ["sse_starlette", "sse_starlette.sse"]
hidden += ["reverse_geocoder", "scipy.spatial", "scipy.spatial.ckdtree"]

a = Analysis(
    ["../src/bl_tracker/__main__.py"],
    pathex=["../src"],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="bl-tracker",
    debug=False, strip=False, upx=False,
    console=True,
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False,
    name="bl-tracker",
)
