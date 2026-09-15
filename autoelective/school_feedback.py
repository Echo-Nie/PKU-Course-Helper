"""Classify school feedback without depending on live clients or configuration."""
import re
import unicodedata

from . import exceptions as errors


def normalized(text):
    value = unicodedata.normalize('NFKC', str(text or '')).casefold()
    value = re.sub(r'^\s*\[\d+\]\s*', '', value)
    return re.sub(r'[\s\u200b\ufeff,，.。!！:：;；]', '', value)


SYSTEM_PREFIXES = (
    ('token无效', errors.InvalidTokenError),
    ('您尚未登录或者会话超时', errors.SessionExpiredError),
    ('尚未登录或者会话超时', errors.SessionExpiredError),
    ('请不要用刷课机刷课', errors.CaughtCheatingError),
    ('索引错误', errors.CourseIndexError),
    ('验证码不正确', errors.CaptchaError),
    ('无验证信息', errors.NoAuthInfoError),
    ('你与他人共享了回话', errors.SharedSessionError),
    ('你与他人共享了会话', errors.SharedSessionError),
    ('只有同意选课协议才可以继续选课', errors.NotAgreedToSelectionAgreement),
    ('不在操作时段', errors.NotInOperationTimeError),
)
TIPS_PREFIXES = (
    ('您已经选过该课程了', errors.ElectionRepeatedError),
    ('对不起超时操作请重新登录', errors.OperationTimeoutError),
    ('超时操作请重新登录', errors.OperationTimeoutError),
    ('选课操作失败请稍后再试', errors.ElectionFailedError),
    ('您本学期所选课程的总学分已经超过规定学分上限', errors.CreditsLimitedError),
    ('学校规定每学期只能修一门英语课', errors.MultiEnglishCourseError),
    ('学校规定每学期只能修一门体育课', errors.MultiPECourseError),
    ('上课时间冲突', errors.TimeConflictError),
    ('考试时间冲突', errors.ExamTimeConflictError),
    ('该课程在补退选阶段开始后的约一周开放选课', errors.ElectionPermissionError),
    ('该课程选课人数已满', errors.QuotaLimitedError),
)


def system_exception(text):
    value = normalized(text)
    for prefix, kind in SYSTEM_PREFIXES:
        if value.startswith(prefix):
            return kind
    if re.search(r'^目前不是.+时间因此不能进行相应操作', value):
        return errors.NotInOperationTimeError
    return errors.SystemException


def tips_exception(text):
    value = normalized(text)
    for prefix, kind in TIPS_PREFIXES:
        if value.startswith(prefix):
            return kind
    if value == '补选课程成功' or value.startswith('补选课程成功请查看已选'):
        return errors.ElectionSuccess
    if re.search(r'^补选\(或者候补\)课程.*成功请查看已选上列表确认', value):
        return errors.ElectionSuccess
    if value == '只能选其一门' or re.search(r'.+与.+只能选其一门', value):
        return errors.MutexCourseError
    return errors.TipsException
