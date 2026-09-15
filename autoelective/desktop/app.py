"""Native Windows shell hosting the bundled React UI without a web server."""
import base64
import os
from pathlib import Path
import shutil
import sys
import time

from .bridge import DesktopBridge
from .platform.instance import acquire_instance


_BRIDGE_METHODS = ('bootstrap', 'save', 'start', 'stop', 'poll', 'set_dirty',
                   'import_config', 'export_config', 'clear_data', 'open_external_link')


def _install_native_boundary(window, bridge):
    """Install on before_show (UI thread) using locked pywebview 6.2.1 APIs.

    The renderer's native control exists at before_show; its CoreWebView2 may
    finish initializing later. No Python functions are exposed before both
    navigation guards are in place.
    """
    native = window.native
    renderer = native.browser
    control = native.webview
    # Recent WebView2 versions report NavigateToString as a data URL, while
    # older versions report about:blank. Pin the exact bundled document once;
    # allowing an arbitrary data: origin would expose our privileged bridge.
    inline_uri = 'data:text/html;charset=utf-8;base64,' + base64.b64encode(
        window.html.encode('utf-8')).decode('ascii')

    def deny_navigation(sender, args):
        uri = str(args.Uri)
        document = uri.partition('#')[0]
        if getattr(args, 'IsRedirected', False) or document not in ('about:blank', inline_uri):
            args.Cancel = True

    def deny_frame_navigation(sender, args):
        args.Cancel = True

    def deny_new_window(sender, args):
        args.Handled = True

    control.NavigationStarting += deny_navigation
    installed = False

    def attach_core():
        nonlocal installed
        if installed:
            return
        core = control.CoreWebView2
        # pywebview's default handler loads target=_blank into this privileged
        # window when OPEN_EXTERNAL_LINKS_IN_BROWSER=False. Remove that handler.
        core.NewWindowRequested -= renderer.on_new_window_request
        core.NewWindowRequested += deny_new_window
        core.FrameNavigationStarting += deny_frame_navigation
        window.expose(*(getattr(bridge, name) for name in _BRIDGE_METHODS))
        installed = True

    def initialized(sender, args):
        if not args.IsSuccess:
            window._runtime_error = True
            native.Close()
            return
        try:
            attach_core()
        except Exception:
            window._boundary_error = True
            native.Close()

    # Retain delegates for the full native window lifetime.
    window._navigation_guards = (deny_navigation, deny_frame_navigation, deny_new_window, initialized)
    if control.CoreWebView2 is not None:
        attach_core()
    else:
        control.CoreWebView2InitializationCompleted += initialized


def run(paths, instance=None):
    if os.name != 'nt':
        raise RuntimeError('桌面外壳面向 Windows。开发预览：在 frontend 运行 npm run dev，打开 /?preview=1。')
    owns_instance = instance is None
    handle, kernel = acquire_instance() if owns_instance else instance
    if handle is None:
        return 0
    bridge = None
    try:
        import webview
        from .adapters.webview_runtime import private_runtime
        runtime = private_runtime(paths.root)
        webview.settings['WEBVIEW2_RUNTIME_PATH'] = str(runtime) if runtime else None
        resource_root = Path(getattr(sys, '_MEIPASS', paths.root))
        html_path = resource_root / 'frontend' / 'dist' / 'index.html'
        if not html_path.is_file():
            raise RuntimeError('界面资源缺失，请重新解压完整软件包。开发环境请先运行 frontend 的 npm run build。')
        bridge = DesktopBridge(paths)
        bridge._supervisor.recover_power()
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False
        webview.settings['OPEN_DEVTOOLS_IN_DEBUG'] = False
        webview.settings['REMOTE_DEBUGGING_PORT'] = None
        webview.settings['ALLOW_DOWNLOADS'] = False
        webview.settings['ALLOW_FILE_URLS'] = False
        # Inline built assets avoid pywebview's implicit local-file HTTP server.
        window = webview.create_window('PKUCourseHelper', html=html_path.read_text(encoding='utf-8'),
                                       width=1220, height=840, min_size=(760, 560),
                                       background_color='#f5f3f0', text_select=True, zoomable=True)
        bridge._window = window

        def before_show():
            try:
                _install_native_boundary(window, bridge)
            except Exception:
                window._boundary_error = True
                window.native.Close()

        window.events.before_show += before_show

        def closing():
            with bridge._state_lock:
                dirty = bridge._dirty
            active = bridge._supervisor.is_active
            if active or dirty:
                prompt = '退出会停止正在运行的任务。' if active else ''
                if dirty:
                    prompt += '未保存的修改将丢失。'
                if not window.create_confirmation_dialog('退出工作台', prompt + '是否退出？'):
                    return False
            return bool(bridge._shutdown())

        window.events.closing += closing
        # Explicit renderer: never fall back to MSHTML/Qt or install a runtime.
        try:
            webview.start(gui='edgechromium', debug=False, http_server=False,
                          private_mode=True, storage_path=str(paths.cache / 'webview'))
        except Exception as error:
            message = ('无法启动软件私有 WebView2，请重新解压完整软件包；安装版请重新安装。' if runtime else
                       '无法启动 Windows WebView2。请使用已具备 WebView2 的 Windows；本软件不会安装系统组件。')
            raise RuntimeError(message) from error
        if getattr(window, '_runtime_error', False):
            message = ('软件私有 WebView2 初始化失败，请重新解压完整软件包；安装版请重新安装。' if runtime else
                       'Windows WebView2 初始化失败。请修复系统 WebView2 运行时后重试；本软件不会安装系统组件。')
            raise RuntimeError(message)
        if getattr(window, '_boundary_error', False):
            raise RuntimeError('无法初始化本地窗口保护，请重新解压完整软件包。')
    finally:
        if bridge:
            bridge._shutdown()
            if getattr(bridge, '_clear_profile_on_exit', False):
                for _ in range(10):
                    try:
                        shutil.rmtree(paths.cache)
                        break
                    except FileNotFoundError:
                        break
                    except OSError:
                        time.sleep(0.1)
        if owns_instance:
            kernel.CloseHandle(handle)
    return 0
