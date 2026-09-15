import ast
import base64
import inspect
from types import SimpleNamespace

import pytest

from autoelective.desktop import app


class NativeEvent:
    def __init__(self, *handlers):
        self.handlers = list(handlers)

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def __isub__(self, handler):
        self.handlers.remove(handler)
        return self

    def emit(self, args):
        for handler in list(self.handlers):
            handler(None, args)


def fake_window(ready=True):
    navigations = []
    default_handler = lambda sender, args: navigations.append(args.Uri)
    core = SimpleNamespace(NewWindowRequested=NativeEvent(default_handler), FrameNavigationStarting=NativeEvent())
    control = SimpleNamespace(NavigationStarting=NativeEvent(), CoreWebView2=core if ready else None,
                              CoreWebView2InitializationCompleted=NativeEvent())
    exposed = {}
    closed = []
    window = SimpleNamespace(html='<!doctype html><html lang="zh-CN"><body>PKUCourseHelper</body></html>', native=SimpleNamespace(webview=control,
                             browser=SimpleNamespace(on_new_window_request=default_handler),
                             Close=lambda: closed.append(True)),
                             expose=lambda *functions: exposed.update({f.__name__: f for f in functions}))
    return window, core, exposed, navigations, closed


class Bridge:
    def bootstrap(self): pass
    def save(self): pass
    def start(self): pass
    def stop(self): pass
    def poll(self): pass
    def set_dirty(self): pass
    def import_config(self): pass
    def export_config(self): pass
    def clear_data(self): pass
    def open_external_link(self): pass
    def _shutdown(self): pass


def test_app_does_not_pass_object_graph_as_js_api():
    source = ast.parse(inspect.getsource(app.run))
    create = [node for node in ast.walk(source)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == 'create_window']
    assert len(create) == 1
    assert 'js_api' not in {keyword.arg for keyword in create[0].keywords}


def test_only_explicit_functions_exposed_after_native_guards():
    window, core, exposed, navigations, closed = fake_window()
    app._install_native_boundary(window, Bridge())
    assert set(exposed) == {'bootstrap', 'save', 'start', 'stop', 'poll', 'set_dirty',
                            'import_config', 'export_config', 'clear_data', 'open_external_link'}
    args = SimpleNamespace(Uri='https://example.invalid', Handled=False)
    core.NewWindowRequested.emit(args)
    assert args.Handled
    assert navigations == []  # pywebview's in-window navigation handler was removed.
    assert not closed


@pytest.mark.parametrize('uri', ['https://example.invalid', 'file:///C:/private.txt',
                                  'data:text/html,test', 'javascript:alert(1)', 'about:srcdoc'])
def test_remote_file_and_executable_navigation_denied_for_top_and_frame(uri):
    window, core, exposed, navigations, closed = fake_window()
    app._install_native_boundary(window, Bridge())
    for event in (window.native.webview.NavigationStarting, core.FrameNavigationStarting):
        args = SimpleNamespace(Uri=uri, Cancel=False)
        event.emit(args)
        assert args.Cancel


@pytest.mark.parametrize('uri', ['about:blank', 'about:blank#courses'])
def test_inline_document_and_same_document_fragment_remain_allowed(uri):
    window, core, exposed, navigations, closed = fake_window()
    app._install_native_boundary(window, Bridge())
    args = SimpleNamespace(Uri=uri, Cancel=False)
    window.native.webview.NavigationStarting.emit(args)
    assert not args.Cancel


def test_delayed_webview_initialization_exposes_nothing_until_guards_installed():
    window, core, exposed, navigations, closed = fake_window(ready=False)
    app._install_native_boundary(window, Bridge())
    assert exposed == {}
    window.native.webview.CoreWebView2 = core
    window.native.webview.CoreWebView2InitializationCompleted.emit(SimpleNamespace(IsSuccess=True))
    assert set(exposed) == set(app._BRIDGE_METHODS)
    # A duplicate initialized notification must not duplicate handlers.
    window.native.webview.CoreWebView2InitializationCompleted.emit(SimpleNamespace(IsSuccess=True))
    assert len(core.NewWindowRequested.handlers) == 1


def test_native_guard_failure_does_not_expose_bridge():
    window, core, exposed, navigations, closed = fake_window(ready=False)
    app._install_native_boundary(window, Bridge())
    window.native.webview.CoreWebView2 = SimpleNamespace()
    window.native.webview.CoreWebView2InitializationCompleted.emit(SimpleNamespace(IsSuccess=True))
    assert exposed == {}
    assert closed == [True]
    assert window._boundary_error


def inline_uri(window):
    return 'data:text/html;charset=utf-8;base64,' + base64.b64encode(window.html.encode('utf-8')).decode('ascii')


def test_webview2_inline_navigation_accepts_exact_bundled_html():
    window, core, exposed, navigations, closed = fake_window()
    app._install_native_boundary(window, Bridge())
    args = SimpleNamespace(Uri=inline_uri(window), Cancel=False, IsRedirected=False)
    window.native.webview.NavigationStarting.emit(args)
    assert not args.Cancel


def test_inline_document_fragment_remains_on_trusted_document():
    window, core, exposed, navigations, closed = fake_window()
    app._install_native_boundary(window, Bridge())
    args = SimpleNamespace(Uri=inline_uri(window) + '#courses', Cancel=False)
    window.native.webview.NavigationStarting.emit(args)
    assert not args.Cancel


def test_even_blank_subframes_are_not_privileged_documents():
    window, core, exposed, navigations, closed = fake_window()
    app._install_native_boundary(window, Bridge())
    args = SimpleNamespace(Uri='about:blank', Cancel=False)
    core.FrameNavigationStarting.emit(args)
    assert args.Cancel


@pytest.mark.parametrize('suffix', ['', '#courses'])
def test_trusted_inline_document_cannot_be_embedded_in_a_frame(suffix):
    window, core, exposed, navigations, closed = fake_window()
    app._install_native_boundary(window, Bridge())
    args = SimpleNamespace(Uri=inline_uri(window) + suffix, Cancel=False)
    core.FrameNavigationStarting.emit(args)
    assert args.Cancel


@pytest.mark.parametrize('suffix', ['evil', '?other=1', '%23courses'])
def test_modified_inline_payload_is_not_a_trusted_document(suffix):
    window, core, exposed, navigations, closed = fake_window()
    app._install_native_boundary(window, Bridge())
    args = SimpleNamespace(Uri=inline_uri(window) + suffix, Cancel=False)
    window.native.webview.NavigationStarting.emit(args)
    assert args.Cancel


def test_redirect_to_inline_payload_does_not_bypass_navigation_guard():
    window, core, exposed, navigations, closed = fake_window()
    app._install_native_boundary(window, Bridge())
    args = SimpleNamespace(Uri=inline_uri(window), Cancel=False, IsRedirected=True)
    window.native.webview.NavigationStarting.emit(args)
    assert args.Cancel


def test_native_initialization_failure_closes_without_exposing_bridge():
    window, core, exposed, navigations, closed = fake_window(ready=False)
    app._install_native_boundary(window, Bridge())
    window.native.webview.CoreWebView2InitializationCompleted.emit(SimpleNamespace(IsSuccess=False))
    assert exposed == {}
    assert closed == [True]
    assert window._runtime_error
