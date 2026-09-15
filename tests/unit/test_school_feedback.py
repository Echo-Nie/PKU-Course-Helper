from types import SimpleNamespace
from urllib.parse import quote

import pytest

from autoelective import exceptions as errors
from autoelective.school_feedback import system_exception, tips_exception
from autoelective.desktop.runtime.feedback import describe_error, safe_school_text
from autoelective.desktop.runtime.school_session import SchoolSession
from autoelective.parser import get_tree, get_errInfo, get_tips


SYSTEM_CASES = [
    ('Token无效', 'InvalidTokenError'),
    (' token 无效。 ', 'InvalidTokenError'),
    ('[310] 您尚未登录或者会话超时，请重新登录。', 'SessionExpiredError'),
    ('尚未登录或者会话超时', 'SessionExpiredError'),
    ('请不要用刷课机刷课，否则会受到学校严厉处分！', 'CaughtCheatingError'),
    ('不在操作时段', 'NotInOperationTimeError'),
    ('目前不是补退选时间，因此不能进行相应操作。', 'NotInOperationTimeError'),
    ('索引错误。', 'CourseIndexError'),
    ('验证码不正确。', 'CaptchaError'),
    ('无验证信息。', 'NoAuthInfoError'),
    ('你与他人共享了回话，请退出浏览器重新登录。', 'SharedSessionError'),
    ('你与他人共享了会话，请退出浏览器重新登录。', 'SharedSessionError'),
    ('只有同意选课协议才可以继续选课！', 'NotAgreedToSelectionAgreement'),
    ('新的学校系统反馈', 'SystemException'),
]
TIPS_CASES = [
    ('补选课程成功', 'ElectionSuccess'),
    ('补选（或者候补）课程示例成功，请查看已选上列表确认，并查看选课结果。', 'ElectionSuccess'),
    ('您已经选过该课程了。', 'ElectionRepeatedError'),
    ('上课时间冲突：与另一课程冲突', 'TimeConflictError'),
    ('考试时间冲突', 'ExamTimeConflictError'),
    ('对不起，超时操作，请重新登录。', 'OperationTimeoutError'),
    ('超时操作，请重新登录', 'OperationTimeoutError'),
    ('该课程在补退选阶段开始后的约一周开放选课', 'ElectionPermissionError'),
    ('您本学期所选课程的总学分已经超过规定学分上限。', 'CreditsLimitedError'),
    ('选课操作失败，请稍后再试。', 'ElectionFailedError'),
    ('只能选其一门', 'MutexCourseError'),
    ('高等代数与线性代数只能选其一门。', 'MutexCourseError'),
    ('学校规定每学期只能修一门英语课', 'MultiEnglishCourseError'),
    ('学校规定每学期只能修一门体育课。', 'MultiPECourseError'),
    ('该课程选课人数已满。', 'QuotaLimitedError'),
    ('新的学校提交反馈', 'TipsException'),
]


@pytest.mark.parametrize('text,name', SYSTEM_CASES)
def test_system_pages_keep_specific_feedback_and_processing_action(text, name):
    kind = system_exception(text)
    assert kind.__name__ == name
    message = describe_error(kind(msg=text))
    assert text.strip() in message and name in message and '处理：' in message


@pytest.mark.parametrize('text,name', TIPS_CASES)
def test_tips_keep_specific_feedback_and_processing_action(text, name):
    kind = tips_exception(text)
    assert kind.__name__ == name
    message = describe_error(kind(msg=text))
    assert text in message and name in message and '处理：' in message


@pytest.mark.parametrize('name,status,fragment', [
    ('ElectionSuccess', 'unconfirmed', '以已选列表确认'),
    ('ElectionRepeatedError', 'ignored', '同课号'),
    ('TimeConflictError', 'ignored', '上课时间冲突'),
    ('ExamTimeConflictError', 'ignored', '考试时间冲突'),
    ('ElectionPermissionError', 'ignored', '跨院系选课尚未开放'),
    ('CreditsLimitedError', 'ignored', '学分上限'),
    ('ElectionFailedError', 'waiting', '本次失败'),
    ('MutexCourseError', 'ignored', '互斥'),
    ('MultiEnglishCourseError', 'ignored', '一门英语课'),
    ('MultiPECourseError', 'ignored', '一门体育课'),
    ('QuotaLimitedError', 'waiting', '人数已满'),
    ('CaptchaError', 'waiting', '验证码'),
    ('CourseIndexError', 'waiting', '索引'),
])
def test_submission_does_not_collapse_different_school_feedback(name, status, fragment):
    session = SchoolSession.__new__(SchoolSession)
    session.username, session.password, session.initialized = 'fixture-user', 'fixture-secret', True
    def submit(*args): raise getattr(errors, name)(response=SimpleNamespace(_tree=get_tree('<html/>')))
    session.client = SimpleNamespace(get_ElectSupplement=submit)
    result, message, elected = session.submit(SimpleNamespace(href='/offline'))
    assert result == status and fragment in message and name in message
    if name == 'CourseIndexError': assert not session.initialized


def test_unknown_feedback_is_bounded_and_redacts_credentials_without_dropping_the_warning():
    password = 'private-pässword&!'
    raw = ('新反馈 ' + password + ' ' + quote(password, safe='') +
           ' 学号：1234567890 token=shortsecret password="another-secret" '
           ' https://offline.invalid/?sida=hidden-url-token\nCookie: JSESSIONID=hidden-cookie\n继续核对\x1b')
    text = describe_error(errors.TipsException(msg=raw), ('1234567890', password))
    assert '未知错误警告' in text and '新反馈' in text and '继续核对' in text
    for private in (password, quote(password, safe=''), '1234567890', 'shortsecret', 'another-secret', 'hidden-url-token', 'hidden-cookie'):
        assert private not in text
    assert '\n' not in text and '\x1b' not in text
    assert len(safe_school_text('长' * 16000)) < 520
    assert '隐藏原文' in safe_school_text('长' * 16001)
    assert 'private' not in describe_error(RuntimeError('private raw exception'))
    assert '无法解析' in describe_error(errors.UnexceptedHTMLFormat())


def test_nested_school_error_text_and_plain_tip_container_are_readable():
    tree = get_tree('<html><table><tr><td><table><tr><td><table><tr><td>'
                    '<strong>出错提示：</strong><span>Token无效</span></td></tr></table></td></tr></table></td></tr></table></html>')
    assert get_errInfo(tree) == 'Token无效'
    assert get_tips(get_tree('<html><table><tr><td id="msgTips">新的<span>反馈</span></td></tr></table></html>')) == '新的反馈'


def test_server_error_and_pe_exception_metadata_are_correct():
    assert errors.ServerError.code == 102
    error = errors.MultiPECourseError(response=SimpleNamespace(), msg='学校规定每学期只能修一门体育课。')
    assert isinstance(error, errors.TipsException) and error.response is not None


@pytest.mark.parametrize('text', ['补选课程成功率未知', '补选（或者候补）课程示例不成功'])
def test_unknown_feedback_is_not_inferred_to_be_success(text):
    assert tips_exception(text) is errors.TipsException
