"""Bounded network operations using the existing school protocol and ONNX model."""
import random
import html
import re
import threading
import time
from urllib.parse import parse_qs, urlparse
from .feedback import describe_error


class IdentityUnavailable(Exception):
    pass


class RetryTurn(Exception):
    pass


def response_object(response):
    try:
        value = response.json()
    except ValueError as error:
        raise RetryTurn('学校响应不完整，将稍后重新查询') from error
    if not isinstance(value, dict):
        raise RetryTurn('学校响应格式异常，将稍后重新查询')
    return value


FATAL_ERRORS = {'AccessLimitedError', 'CaughtCheatingError', 'IAAAIncorrectPasswordError',
                'IAAAForbiddenError', 'NotAgreedToSelectionAgreement'}
AUTH_ERRORS = {'SessionExpiredError', 'InvalidTokenError', 'NoAuthInfoError', 'SharedSessionError',
               'OperationTimeoutError'}
SKIP_ERRORS = {'ElectionRepeatedError', 'TimeConflictError', 'ExamTimeConflictError',
               'ElectionPermissionError', 'CreditsLimitedError', 'MutexCourseError',
               'MultiEnglishCourseError', 'MultiPECourseError'}


def identity_options(response):
    """Read actual selector links; never infer minor access from user settings."""
    from autoelective.parser import get_tree
    tree = getattr(response, '_tree', None)
    if tree is None:
        tree = get_tree(response.text)
    if tree is None:
        return {}
    choices = {}
    for href in tree.xpath('//a/@href'):
        query = parse_qs(urlparse(href).query)
        sttp, sida = query.get('sttp', [''])[0], query.get('sida', [''])[0]
        if sttp in ('bzx', 'bfx') and re.fullmatch(r'[A-Za-z0-9]{32}', sida):
            choices[sttp] = sida
    # Historical selector variants embed these same URLs in onclick/script.
    for sida, sttp in re.findall(r'[?&]sida=([A-Za-z0-9]{32})&sttp=(bzx|bfx)(?=[\s\x22\x27<>&]|$)',
                                  html.unescape(response.text)):
        choices[sttp] = sida
    return choices


class SchoolSession:
    def __init__(self, slot_id, config, password, recognizer, recognition_lock=None):
        from autoelective.elective import ElectiveClient
        self.config, self.password = config, password
        self.username = config.user['student_id'].strip()
        self.client = ElectiveClient(slot_id, timeout=config.client['elective_client_timeout'])
        self.recognizer = recognizer
        self.recognition_lock = recognition_lock or threading.Lock()
        self.identity = None
        self.initialized = False
        self.ready = False
        self.expires_at = 0

    def ensure_login(self, identity, budget):
        if self.ready and self.identity == identity and time.monotonic() < self.expires_at:
            return False
        from autoelective.iaaa import IAAAClient
        from autoelective.const import USER_AGENT_LIST
        budget.wait()
        if self.ready:
            try:
                self.client.logout()
            except Exception as error:
                if type(error).__name__ in FATAL_ERRORS:
                    raise
        self.ready = False
        self.initialized = False
        self.identity = None
        self.client.clear_cookies()
        agent = random.choice(USER_AGENT_LIST)
        self.client.set_user_agent(agent)
        iaaa = IAAAClient(timeout=self.config.client['iaaa_client_timeout'])
        iaaa.set_user_agent(agent)
        try:
            iaaa.oauth_home()
            response = iaaa.oauth_login(self.username, self.password)
            token = response_object(response).get('token')
            if not isinstance(token, str) or not token:
                raise RetryTurn('认证响应缺少有效令牌')
            response = self.client.sso_login(token)
            options = identity_options(response)
            if options:
                if identity not in options:
                    label = '辅修' if identity == 'bfx' else '主修'
                    raise IdentityUnavailable('学校未提供%s选课入口。请手动登录学校系统核对可用身份，再修改课程类别或确认选课资格。' % label)
                self.client.sso_login_dual_degree(options[identity], identity, response.url)
            elif identity == 'bfx':
                raise IdentityUnavailable('未识别到辅修选课入口。若该课属于主修或普通选修，请修改课程类别；若网页可以进入辅修，请检查入口识别兼容性。')
            lifetime = self.config.client['elective_client_max_life']
            self.expires_at = float('inf') if lifetime == -1 else time.monotonic() + lifetime
            self.client.set_expired_time(-1)  # Desktop lifetime uses a monotonic clock.
            self.identity, self.ready = identity, True
            return True
        finally:
            iaaa._session.close()

    @staticmethod
    def parse(response):
        from autoelective.parser import get_tables, get_courses, get_courses_with_detail
        try:
            tables = get_tables(response._tree)
            return get_courses(tables[1]), get_courses_with_detail(tables[0])
        except (IndexError, ValueError, AttributeError, TypeError) as error:
            raise RetryTurn('无法读取完整选课页面') from error

    def fetch(self, page, budget):
        # At most one first-page initialization and one target-page request.
        # Each request takes a separate FIFO grant; there is no local retry loop.
        if page > 1 and not self.initialized:
            budget.wait()
            self.parse(self.client.get_SupplyCancel(self.username))
            self.initialized = True
        budget.wait()
        response = (self.client.get_SupplyCancel(self.username) if page == 1
                    else self.client.get_supplement(self.username, page=page))
        try:
            result = self.parse(response)
            self.initialized = True
            return result
        except RetryTurn:
            self.initialized = False
            raise

    def prepare(self):
        # Exactly one captcha attempt per turn, then yield on failure.
        response = self.client.get_DrawServlet()
        try:
            with self.recognition_lock:
                captcha = self.recognizer.recognize(response.content)
        except ValueError as error:
            raise RetryTurn('验证码内容异常，将重新获取后重试') from error
        result = response_object(self.client.get_Validate(self.username, captcha.code))
        if result.get('valid') != '2':
            raise RetryTurn('本次验证码未通过，将归还会话并稍后重试')

    def submit(self, course):
        try:
            self.client.get_ElectSupplement(course.href)
        except Exception as error:
            name = type(error).__name__
            reason = describe_error(error, (getattr(self, 'username', ''), getattr(self, 'password', '')))
            if name == 'ElectionSuccess':
                from autoelective.parser import get_tables, get_courses
                try:
                    elected = get_courses(get_tables(error.response._tree)[1])
                except (IndexError, ValueError, AttributeError, TypeError):
                    elected = []
                return 'unconfirmed', reason, elected
            if name in SKIP_ERRORS:
                return 'ignored', reason, []
            if name in {'ElectionFailedError', 'QuotaLimitedError', 'CaptchaError', 'CourseIndexError'}:
                if name == 'CourseIndexError':
                    self.initialized = False
                return 'waiting', reason, []
            raise
        return 'unconfirmed', '未知错误警告：提交后没有可识别的反馈；结果待核对，不会重复提交', []

    def invalidate(self):
        self.ready = False
        self.initialized = False

    def reset_transport(self):
        # Retire stale TCP/proxy pools after a Wi-Fi change or dropped response.
        # Keep valid cookies, and let normal auth errors trigger re-login. There
        # is no adapter-level retry: a submission must never be replayed here.
        self.client._session.close()
        self.initialized = False

    def close(self):
        self.password = None
        self.client._session.close()
