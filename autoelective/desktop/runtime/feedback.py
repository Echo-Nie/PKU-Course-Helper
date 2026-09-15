"""Bounded, credential-safe school feedback for the existing desktop log."""
import html
import re
from urllib.parse import quote, quote_plus

from autoelective import exceptions as errors


ERROR_REASONS = {
    'ConnectTimeout': '连接学校服务器超时', 'ReadTimeout': '学校响应超时',
    'Timeout': '网络请求超时', 'ConnectionError': '连接中断或网络暂不可用',
    'ProxyError': '代理连接失败，请检查本机网络代理', 'SSLError': '安全连接校验失败',
    'JSONDecodeError': '学校返回了无法解析的响应',
    'ChunkedEncodingError': '学校响应在传输途中中断，将重新连接',
    'ContentDecodingError': '学校响应内容损坏，将重新查询',
    'ServerError': '学校服务器暂时异常', 'StatusCodeError': '学校返回异常状态码',
    'IAAANotSuccessError': '统一认证未成功，稍后重试',
    'OperationFailedError': '学校操作失败，原因未明确',
    'UnexceptedHTMLFormat': '学校页面结构无法解析，将按退避策略重新查询',
}
SCHOOL_ACTIONS = {
    'CaughtCheatingError': '学校已限制本次访问，任务安全停止；不自动重试，请先在学校网页核对。仅凭此提示不能确定是否为 Referer 或验证码流程问题',
    'InvalidTokenError': '登录令牌失效，将重新登录独立会话',
    'SessionExpiredError': '会话已过期，将重新登录；桌面版按课程身份自动选择主修/辅修，无需设置 dual_degree',
    'NotInOperationTimeError': '当前不在学校允许的操作时段，将退避后查询；请核对学校补退选开放时间',
    'CourseIndexError': '课程索引已失效，将重新初始化并查询页面，不复用旧选课链接',
    'CaptchaError': '本次验证码未通过，将归还会话并在后续轮次重新验证',
    'NoAuthInfoError': '学校未返回验证信息，将更新会话；如反复出现，请核对课程身份与学校提供的身份入口',
    'SharedSessionError': '会话冲突，将重新登录独立会话；请核对账号，不要在同一会话内切换账号',
    'NotAgreedToSelectionAgreement': '任务已停止；请先在学校网页阅读并同意选课协议，再手动启动',
    'ElectionSuccess': '学校提示提交成功，仍以已选列表确认；确认前不会重复提交',
    'ElectionRepeatedError': '本次跳过；可能已选同课号的其他班或开课单位，请核对已选列表',
    'TimeConflictError': '上课时间冲突，本次跳过，不会自动退掉已有课程',
    'ExamTimeConflictError': '考试时间冲突，本次跳过，不会自动退掉已有课程',
    'OperationTimeoutError': '会话操作超时，将重新登录并核对已选结果',
    'ElectionPermissionError': '跨院系选课尚未开放或当前权限不满足，本次跳过；开放后请重新运行',
    'CreditsLimitedError': '已超过学分上限，本次跳过；不会自动退课',
    'ElectionFailedError': '学校明确反馈本次失败，将等待下一轮查询，不立即重复请求',
    'MutexCourseError': '学校互斥限制，本次跳过，请核对已选列表',
    'MultiEnglishCourseError': '超过每学期一门英语课限制，本次跳过',
    'MultiPECourseError': '超过每学期一门体育课限制，本次跳过',
    'QuotaLimitedError': '该课人数已满，以提交时学校结果为准，将重新查询名额',
}


def safe_school_text(value, secrets=()):
    if not isinstance(value, str):
        return '学校未提供可读的提示文本'
    if len(value) > 16_000:
        return '学校反馈过长，已隐藏原文；请在学校网页核对'
    value = html.unescape(html.unescape(value))
    # Remove known in-memory credentials before truncation, including URL forms.
    for secret in sorted({s for s in secrets if isinstance(s, str) and s}, key=len, reverse=True):
        for form in {secret, quote(secret, safe=''), quote_plus(secret)}:
            value = value.replace(form, '[已隐藏]')
    value = re.sub(r'<[^<>]*>', '', value)
    value = re.sub(r'https?://[^\s<>"\u201c\u201d]+', '[链接已隐藏]', value, flags=re.I)
    value = re.sub(r'\b(?:set-cookie|cookie|authorization)\s*[:=][^\r\n]*', '[认证头已隐藏]', value, flags=re.I)
    keys = r'(?:student[_-]?id|user(?:name|_id)?|password|passwd|pwd|(?:access_|refresh_)?token|session(?:id)?|jsessionid|sida|学号|密码|口令|令牌)'
    value = re.sub(r'(?i)(?<![A-Za-z0-9_])(' + keys + r')[\s"\u0027]*[:=：]\s*(?:"[^"]*"|\u0027[^\u0027]*\u0027|[^\s,，;；<>]+)', r'\1=[已隐藏]', value)
    value = re.sub(r'(?i)\bbearer\s+\S+', 'Bearer [已隐藏]', value)
    value = re.sub(r'(?<![A-Za-z0-9])[A-Za-z0-9_\-]{24,}(?![A-Za-z0-9])', '[标识已隐藏]', value)
    value = re.sub(r'(?<!\d)\d{8,14}(?!\d)', '[数字标识已隐藏]', value)
    value = re.sub(r'[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]', ' ', value)
    value = ' '.join(value.split())
    return value[:500] + ('…（已截断）' if len(value) > 500 else '') or '学校提示文本为空'


def describe_error(error, secrets=()):
    name = type(error).__name__
    if isinstance(error, (errors.SystemException, errors.TipsException)):
        category = '系统异常' if isinstance(error, errors.SystemException) else '选课提示'
        raw = safe_school_text(getattr(error, 'detail', error.desc), secrets)
        action = SCHOOL_ACTIONS.get(name)
        prefix = '' if action else '未知错误警告：'
        return '%s%s [%s %s]：%s；处理：%s' % (prefix, category, error.code, name, raw,
                action or '保留警告并退避核对；若已提交则等待已选列表确认，不自动重放')
    if name == 'RetryTurn':
        return safe_school_text(str(error), secrets)
    reason = ERROR_REASONS.get(name)
    if reason:
        status = getattr(getattr(error, 'response', None), 'status_code', None)
        http = '，HTTP %d' % status if type(status) is int and 100 <= status <= 599 else ''
        return '%s（%s%s）' % (reason, name, http)
    return '未知错误警告（%s）；未记录可能含敏感数据的原始异常，请核对运行记录' % name
