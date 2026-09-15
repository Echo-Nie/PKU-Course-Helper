from types import SimpleNamespace
import threading

import pytest

from autoelective.desktop.runtime.school_session import SchoolSession, RetryTurn, identity_options


def test_reads_actual_identity_links_instead_of_global_toggle():
    token = 'a' * 32
    response = SimpleNamespace(text=f'<a href="/sso?sida={token}&amp;sttp=bzx">主修</a>'
                                    f'<a href="/sso?sida={token}&amp;sttp=bfx">辅修</a>')
    assert identity_options(response) == {'bzx': token, 'bfx': token}
    assert identity_options(SimpleNamespace(text='<html><title>选课</title></html>')) == {}
    assert identity_options(SimpleNamespace(text='<a href="?sida=bad&sttp=bfx">bad</a>')) == {}


def test_captcha_failure_yields_after_one_attempt():
    session = SchoolSession.__new__(SchoolSession)
    calls = []
    session.client = SimpleNamespace(
        get_DrawServlet=lambda: calls.append('draw') or SimpleNamespace(content=b'offline'),
        get_Validate=lambda *args: calls.append('validate') or SimpleNamespace(json=lambda: {'valid': '0'}))
    session.username = 'offline'
    session.recognizer = SimpleNamespace(recognize=lambda data: SimpleNamespace(code='TEST'))
    session.recognition_lock = threading.Lock()
    with pytest.raises(RetryTurn):
        session.prepare()
    assert calls == ['draw', 'validate']


def test_page_initialization_and_query_each_take_a_global_grant():
    session = SchoolSession.__new__(SchoolSession)
    session.initialized = False
    session.username = 'offline'
    calls = []
    session.client = SimpleNamespace(get_SupplyCancel=lambda *a: calls.append('first') or 'first',
                                    get_supplement=lambda *a, **kw: calls.append(('page', kw['page'])) or 'page')
    session.parse = lambda response: ([], [])
    budget = SimpleNamespace(wait=lambda: calls.append('grant'))
    session.fetch(3, budget)
    assert calls == ['grant', 'first', 'grant', ('page', 3)]
    calls.clear()
    session.fetch(3, budget)
    assert calls == ['grant', ('page', 3)]


def test_failed_page_parsing_yields_instead_of_looping_recovery():
    session = SchoolSession.__new__(SchoolSession)
    session.initialized = True
    session.username = 'offline'
    calls = []
    session.client = SimpleNamespace(get_supplement=lambda *a, **kw: calls.append('page'))
    def fail(response):
        raise RetryTurn()
    session.parse = fail
    with pytest.raises(RetryTurn):
        session.fetch(2, SimpleNamespace(wait=lambda: None))
    assert calls == ['page'] and not session.initialized
