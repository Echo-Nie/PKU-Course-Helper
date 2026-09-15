import pytest

from autoelective.exceptions import IAAAIncorrectPasswordError
from autoelective.desktop.domain.config import AppConfig, CourseConfig, validate
from autoelective.desktop.runtime.worker import safe_error
from autoelective.desktop.runtime.rules import RuleBook
from autoelective.desktop.adapters.ini_codec import export_ini, import_ini
from autoelective.desktop.adapters.config_service import ConfigService


@pytest.mark.parametrize('detail,expected', [
    ('用户名不存在', '账号不存在'),
    ('密码错误', '密码不正确'),
    ('账号或密码错误', '账号或密码不正确'),
    ('User ID or Password is incorrect', '账号或密码不正确'),
])
def test_auth_feedback_only_distinguishes_explicit_school_responses(detail, expected):
    result = safe_error(IAAAIncorrectPasswordError(msg=detail + ' password=secret-value'))
    assert expected in result
    assert 'secret-value' not in result


@pytest.mark.parametrize('identity,label', [('bzx', '主修 / 选修'), ('bfx', '辅修')])
def test_missing_course_explains_the_identity_and_page(identity, label):
    config = AppConfig(courses=[CourseConfig(id='a', name='课程', school='学院', class_no=0, page=3, identity=identity)])
    book = RuleBook(config)
    book.observe((identity, 3), [], [])
    row = book.snapshot()[0]
    assert row['status'] == 'unmatched'
    assert label in row['reason'] and '第 3 页' in row['reason']
    assert '班号' in row['reason'] and '开课单位' in row['reason']


def test_elective_category_survives_disk_and_ini_without_changing_engine_identity(tmp_path):
    config = AppConfig(courses=[CourseConfig(id='a', name='课程', school='学院', class_no=0)])
    config.extra_json['course_categories'] = {'a': 'elective'}
    service = ConfigService(tmp_path)
    service.save(config)
    loaded = service.load()
    assert loaded.to_dict()['course_categories'] == {'a': 'elective'}
    export_ini(loaded, tmp_path / 'courses.ini')
    imported, _ = import_ini(tmp_path / 'courses.ini')
    assert imported.to_dict()['course_categories'] == {'a': 'elective'}
    assert imported.courses[0].identity == 'bzx'
    assert RuleBook(imported).route['a'] == ('bzx', 1)
    assert validate(imported) == []


def test_native_preview_cannot_start_a_school_session():
    from autoelective.desktop.preview import PreviewBridge
    # No supervisor or credential store is attached: the preview must reject
    # before touching any of the live bridge's machinery.
    bridge = PreviewBridge.__new__(PreviewBridge)
    result = bridge.start({}, password='example-only')
    assert result['ok'] is False
    assert '离线预览' in result['error']
    assert bridge.import_config()['ok'] is False
