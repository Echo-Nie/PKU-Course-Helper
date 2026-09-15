"""Exercise actual response hooks under offline desktop configuration."""
import html
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
cases = json.loads(sys.stdin.read())
output = sys.stdout
sys.stdout = io.StringIO()
import requests
requests.sessions.Session.send = lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Network prohibited'))
from autoelective.desktop.domain.config import AppConfig
from autoelective.desktop.adapters.ini_codec import to_parser
from autoelective.environ import Environ
from autoelective.config import AutoElectiveConfig
config = AppConfig()
config.user['student_id'] = '0000000000'
Environ().config_parser = to_parser(config, password='fixture-password')
AutoElectiveConfig()
from autoelective import hook
from autoelective.desktop.runtime.feedback import describe_error

results = []
for category, message in cases:
    escaped = html.escape(message)
    if category == 'system':
        body = '<head><title> 系统异常 </title></head><table><tr><td><table><tr><td><table><tr><td><strong>出错提示：</strong><span>' + escaped + '</span></td></tr></table></td></tr></table></td></tr></table>'
    elif category == 'malformed':
        body = '<head><title>系统异常</title></head><body>do-not-log-whole-page</body>'
    else:
        body = '<table><tr><td id="msgTips"><table><tr><td><table><tr><td>图标</td><td>' + escaped + '</td></tr></table></td></tr></table></td></tr></table>'
    response = requests.Response()
    response._content = ('<html>' + body + '</html>').encode('utf-8')
    if category == 'empty':
        response._content = b''
    elif category == 'auth-list':
        response._content = b'[]'
    response.encoding = 'utf-8'
    response.request = SimpleNamespace()
    hook.with_etree(response)
    try:
        handler = (hook.check_iaaa_success if category == 'auth-list' else
                   hook.check_elective_title if category in ('system', 'malformed') else hook.check_elective_tips)
        handler(response)
        results.append({'kind': 'not-raised'})
    except Exception as error:
        results.append({'kind': type(error).__name__, 'log': describe_error(error, ('0000000000', 'fixture-password')),
                        'response_retained': getattr(error, 'response', None) is response})
sys.stdout = output
print(json.dumps(results, ensure_ascii=True))  # Stable over Windows' legacy pipe code page.
