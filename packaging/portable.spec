# Windows-only onedir build. Standard PyInstaller hooks retain pywebview's
# WebView2 interop DLLs and pythonnet; the system browser runtime is not bundled.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files

if sys.platform != 'win32':
    raise SystemExit('Build the Windows portable package on Windows x64.')

root = Path(SPECPATH).parent
frontend = root / 'frontend' / 'dist' / 'index.html'
if not frontend.is_file():
    raise SystemExit('Build the frontend first: npm ci && npm run build')

analysis = Analysis(
    [str(root / 'desktop.py')],
    pathex=[str(root)],
    binaries=[],
    datas=collect_data_files('webview', subdir='js') + [
        (str(frontend), 'frontend/dist'),
        (str(root / 'resources' / 'model' / 'captcha.onnx'), 'resources/model'),
        (str(root / 'resources' / 'model' / 'manifest.json'), 'resources/model'),
        (str(root / 'user_agents.txt.gz'), '.'),
    ],
    hiddenimports=[
        'webview.platforms.winforms', 'webview.platforms.edgechromium',
        'pythonnet', 'clr', 'clr_loader',
        'autoelective.desktop.runtime.worker',
        'onnxruntime.capi.onnxruntime_pybind11_state',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tensorflow', 'tf2onnx', 'keras', 'cv2', 'torch', 'onnx',
        'autoelective.captcha.model', 'autoelective.desktop.ui',
        'PySide6', 'PySide2', 'PyQt6', 'PyQt5', 'qtpy', 'gi',
        'cefpython3', 'webview.platforms.qt', 'webview.platforms.gtk',
        'webview.platforms.cocoa', 'webview.platforms.cef',
        'pytest', 'IPython', 'notebook', 'matplotlib', 'scipy',
        'tkinter', 'test', 'tests',
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name='PKUCourseHelper',
    icon=str(root / 'resources' / 'app.ico'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    uac_admin=False,
    uac_uiaccess=False,
    contents_directory='_internal',
)
collect = COLLECT(
    exe, analysis.binaries, analysis.datas,
    strip=False, upx=False, name='PKUCourseHelper',
)
