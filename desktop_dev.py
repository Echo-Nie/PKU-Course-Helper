"""Source-only native development window with loopback Vite hot reload.

Never imported by the packaged entry point. --live uses the production engine;
without it this is an offline UI preview. Passwords always stay in memory.
"""
import argparse
import os
from pathlib import Path
import sys

from autoelective.desktop.bridge import DesktopBridge


class DevelopmentBridge(DesktopBridge):
    """Live mode changes presentation only, never the production run lifecycle."""

    def __init__(self, paths, supervisor=None, *, live=False):
        super().__init__(paths, supervisor)
        self._live = live

    def bootstrap(self):
        result = super().bootstrap()
        result.update(development=True, live=self._live, preview=not self._live,
                      remembered=False, runtime=self.poll())
        return result

    def save(self, config, password='', remember=False):
        return super().save(config, password, False)

    def start(self, config, password='', remember=False):
        if not self._live:
            return {'ok': False, 'error': '离线示例不会登录或选课；请打开“开发版 · 真实选课”窗口。'}
        return super().start(config, password, False)


def install_development_boundary(window, bridge, document_url):
    """Expose the development bridge only after pinning the exact local page."""
    from autoelective.desktop.app import _BRIDGE_METHODS

    native = window.native
    control = native.webview
    renderer = native.browser
    installed = False

    def navigation(sender, args):
        if getattr(args, 'IsRedirected', False) or str(args.Uri).partition('#')[0] != document_url:
            args.Cancel = True

    def frame(sender, args):
        args.Cancel = True

    def new_window(sender, args):
        args.Handled = True

    def attach():
        nonlocal installed
        if installed:
            return
        core = control.CoreWebView2
        core.NewWindowRequested -= renderer.on_new_window_request
        core.NewWindowRequested += new_window
        core.FrameNavigationStarting += frame
        window.expose(*(getattr(bridge, name) for name in _BRIDGE_METHODS))
        installed = True

    def initialized(sender, args):
        try:
            if not args.IsSuccess:
                raise RuntimeError('Development WebView2 initialization failed')
            attach()
        except Exception:
            window._development_error = True
            native.Close()

    control.NavigationStarting += navigation
    window._navigation_guards = (navigation, frame, new_window, initialized)
    if control.CoreWebView2 is not None:
        attach()
    else:
        control.CoreWebView2InitializationCompleted += initialized


def main():
    if os.name != 'nt' or getattr(sys, 'frozen', False):
        raise RuntimeError('Development launcher requires the Windows source environment')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-root', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--port', type=int, default=5173)
    parser.add_argument('--title')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true', help='Enable the full production course engine with frontend hot reload')
    mode.add_argument('--demo', action='store_true', help='Seed an OFFLINE profile with clearly labeled UI test courses')
    args = parser.parse_args()
    instance = None
    try:
        if args.live:
            # Share the production lease: a second live window must not create
            # another uncoordinated pool for the same student account.
            from autoelective.desktop.platform.instance import acquire_instance
            instance = acquire_instance()
            if instance[0] is None:
                raise RuntimeError('已有PKUCourseHelper正在打开，请先正常退出原窗口，再打开真实开发版。')
        return run(args)
    finally:
        if instance and instance[0]:
            instance[1].CloseHandle(instance[0])


def run(args):
    source = Path(__file__).resolve().parent
    profile = args.profile_root.resolve()
    # This launcher is deliberately restricted to the user's testing workspace.
    if source.parent not in profile.parents or profile in (source, args.runtime_root.resolve()):
        raise ValueError('Development profile must be a separate folder inside the testing workspace')
    if not 1024 <= args.port <= 65535:
        raise ValueError('Development port must be between 1024 and 65535')

    from autoelective.desktop.adapters.portable import PortablePaths
    paths = PortablePaths(profile).initialize_environment()
    if args.demo and not paths.settings.exists():
        from autoelective.desktop.domain.config import AppConfig, CourseConfig
        from autoelective.desktop.adapters.config_service import ConfigService
        demo = AppConfig(courses=[
            CourseConfig(id='demo-a', name='界面测试课程 A', school='示例开课单位'),
            CourseConfig(id='demo-b', name='界面测试课程 B', school='示例开课单位', class_no=2),
            CourseConfig(id='demo-c', name='界面测试课程 C', school='示例开课单位', page=2),
            CourseConfig(id='demo-minor', name='界面测试课程 A', school='示例开课单位', identity='bfx'),
        ])
        ConfigService(paths, session_only=True).save(demo)
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(paths.cache / 'webview')
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (
        '--disable-background-networking --disable-component-update --disable-breakpad')

    import socket
    import subprocess
    import time
    from urllib.request import build_opener, ProxyHandler
    import webview
    from autoelective.desktop.adapters.webview_runtime import private_runtime
    from autoelective.desktop.platform.process_tree import ProcessTree

    runtime = private_runtime(args.runtime_root.resolve())
    if runtime is None:
        raise RuntimeError('Development window requires the existing private WebView2 runtime')
    vite = source / 'frontend' / 'node_modules' / 'vite' / 'bin' / 'vite.js'
    if not vite.is_file() or not args.node.is_file():
        raise RuntimeError('Development frontend dependencies or Node executable are missing')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', args.port))
    url = f'http://127.0.0.1:{args.port}/'
    bridge = None
    with (paths.logs / 'vite.log').open('a', encoding='utf-8') as log:
        server = subprocess.Popen(
            [str(args.node), str(vite), '--host', '127.0.0.1', '--port', str(args.port), '--strictPort'],
            cwd=str(source / 'frontend'), stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        server_tree = None
        try:
            server_tree = ProcessTree(server)
            opener = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 20
            while True:
                if server.poll() is not None:
                    raise RuntimeError('Development server exited; see the isolated vite.log')
                try:
                    with opener.open(url, timeout=0.5) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Development server did not become ready')
                time.sleep(0.1)
            webview.settings.update(
                WEBVIEW2_RUNTIME_PATH=str(runtime), OPEN_EXTERNAL_LINKS_IN_BROWSER=False,
                OPEN_DEVTOOLS_IN_DEBUG=False, REMOTE_DEBUGGING_PORT=None,
                ALLOW_DOWNLOADS=False, ALLOW_FILE_URLS=False)
            bridge = DevelopmentBridge(paths, live=args.live)
            if args.live and any(c.id.startswith('demo-') for c in bridge._service.load().courses):
                raise ValueError('此目录含离线示例课程，请为真实选课使用独立的空数据目录。')
            window = webview.create_window(
                args.title or ('PKUCourseHelper · 开发版 · 真实选课（热更新）' if args.live
                               else 'PKUCourseHelper · 离线示例（热更新）'), url=url,
                width=1220, height=840, min_size=(760, 560),
                background_color='#f5f3f0', text_select=True, zoomable=True)
            bridge._window = window

            def before_show():
                try:
                    install_development_boundary(window, bridge, url)
                except Exception:
                    window._development_error = True
                    window.native.Close()

            def closing():
                with bridge._state_lock:
                    dirty = bridge._dirty
                active = bridge._supervisor.is_active
                if active or dirty:
                    prompt = '退出会停止正在运行的真实选课任务。' if active else ''
                    if dirty:
                        prompt += '未保存的修改将丢失。'
                    if not window.create_confirmation_dialog('退出开发工作台', prompt + '是否退出？'):
                        return False
                return bool(bridge._shutdown())

            window.events.before_show += before_show
            window.events.closing += closing
            webview.start(gui='edgechromium', debug=False, http_server=False,
                          private_mode=True, storage_path=str(paths.cache / 'webview'))
            if getattr(window, '_development_error', False):
                raise RuntimeError('Development window navigation protection failed')
        finally:
            if bridge:
                bridge._shutdown()
                if getattr(bridge, '_clear_profile_on_exit', False):
                    import shutil
                    for _ in range(10):
                        try:
                            shutil.rmtree(paths.cache)
                            break
                        except FileNotFoundError:
                            break
                        except OSError:
                            time.sleep(0.1)
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
            if server_tree is not None:
                server_tree.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
