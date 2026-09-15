"""Versioned, password-free desktop configuration and field-level validation."""
import copy
import math
from dataclasses import asdict, dataclass, field
from uuid import uuid4

from .fields import CLIENT_FIELDS

REFRESH_RISK_MESSAGE = '查询过于频繁可能触发访问限制，请将随机偏移后的最短刷新间隔调至不少于 3 秒'


def _id():
    return uuid4().hex


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k.lower() not in {'password', 'passwd', 'secret', 'token'}}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return copy.deepcopy(value)


@dataclass
class CourseConfig:
    id: str = field(default_factory=_id)
    name: str = ''
    class_no: int = 1
    school: str = ''
    page: int = 1
    identity: str = 'bzx'


@dataclass
class MutexRule:
    id: str = field(default_factory=_id)
    courses: list = field(default_factory=list)


@dataclass
class DelayRule:
    id: str = field(default_factory=_id)
    course: str = ''
    threshold: int = 1


@dataclass(repr=False)
class AppConfig:
    schema_version: int = 1
    revision: int = 0
    user: dict = field(default_factory=lambda: {'student_id': ''})
    client: dict = field(default_factory=lambda: {s.key: s.default for s in CLIENT_FIELDS})
    monitor: dict = field(default_factory=lambda: {'host': '127.0.0.1', 'port': 7074})
    courses: list = field(default_factory=list)
    mutexes: list = field(default_factory=list)
    delays: list = field(default_factory=list)
    extra_ini: dict = field(default_factory=dict, repr=False)
    extra_json: dict = field(default_factory=dict, repr=False)

    def __repr__(self):
        return 'AppConfig(schema_version=%r, revision=%r, courses=%d)' % (self.schema_version, self.revision, len(self.courses))

    def to_dict(self):
        result = _clean(self.extra_json)
        result.update({k: _clean(v) for k, v in asdict(self).items() if k != 'extra_json'})
        return result

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('配置内容必须为对象')
        version = value.get('schema_version', 1)
        if type(version) is not int or version != 1:
            raise ValueError('不支持此配置版本，请使用相应版本的软件打开')
        result = cls()
        for key in ('user', 'client', 'monitor'):
            content = value.get(key, {})
            if not isinstance(content, dict):
                raise ValueError('%s 配置格式不正确' % key)
            getattr(result, key).update(_clean(content))
        for key, item_type in (('courses', CourseConfig), ('mutexes', MutexRule), ('delays', DelayRule)):
            entries = value.get(key, [])
            if not isinstance(entries, list):
                raise ValueError('%s 配置必须为列表' % key)
            try:
                if key == 'courses':
                    entries = [dict({'page': result.client['supply_cancel_page'],
                                     'identity': result.user.get('identity', 'bzx')}, **item) for item in entries]
                setattr(result, key, [item_type(**item) for item in entries])
            except (TypeError, ValueError):
                raise ValueError('%s 配置格式不正确' % key) from None
        revision = value.get('revision', 0)
        if type(revision) is not int or revision < 0:
            raise ValueError('配置修订号不正确')
        result.revision = revision
        extra = value.get('extra_ini', {})
        if not isinstance(extra, dict) or any(not isinstance(v, dict) for v in extra.values()):
            raise ValueError('兼容配置格式不正确')
        result.extra_ini = _clean(extra)
        result.extra_json = _clean({k: v for k, v in value.items() if k not in cls.__dataclass_fields__})
        result.user.pop('identity', None)
        result.user.pop('dual_degree', None)
        result.client['print_mutex_rules'] = True
        return result


@dataclass(frozen=True)
class ValidationIssue:
    field_path: str
    code: str
    message: str


def validate(config, for_run=False, password=''):
    issues = []
    def add(path, code, message):
        issues.append(ValidationIssue(path, code, message))
    if type(config.schema_version) is not int or config.schema_version != 1:
        add('schema_version', 'unsupported_version', '不支持此配置版本')
    if type(config.revision) is not int or config.revision < 0:
        add('revision', 'invalid_revision', '配置修订号不正确')
    student = config.user.get('student_id', '')
    if not isinstance(student, str) or any(c in student for c in '\r\n\x00'):
        add('user.student_id', 'invalid_text', '学号格式不正确')
    elif for_run and not student.strip():
        add('user.student_id', 'required', '请填写学号')
    if for_run and not password:
        add('user.password', 'required', '请输入密码')
    for spec in CLIENT_FIELDS:
        if spec.level == 'compatibility':
            continue
        value = config.client.get(spec.key)
        path = 'client.' + spec.key
        if spec.type is bool:
            if type(value) is not bool:
                add(path, 'boolean', '请选择开关值')
            continue
        if (type(value) not in (int, float) or (type(value) is float and not math.isfinite(value))
                or (spec.type is int and type(value) is not int)):
            add(path, 'number', '请输入有效%s' % ('整数' if spec.type is int else '数字'))
        elif spec.key == 'refresh_interval' and value < 3:
            add(path, 'refresh_floor', REFRESH_RISK_MESSAGE)
        elif not spec.min_value <= value <= spec.max_value:
            add(path, 'range', '取值须在 %s 至 %s 之间' % (spec.min_value, spec.max_value))
        elif spec.key == 'elective_client_max_life' and value != -1 and value <= 0:
            add(path, 'positive_integer', '有效期须为正整数或 -1')
    invalid_paths = {i.field_path for i in issues}
    if not invalid_paths.intersection({'client.refresh_interval', 'client.random_deviation'}):
        if config.client['refresh_interval'] * (1 - config.client['random_deviation']) < 3:
            add('client.refresh_interval', 'refresh_floor', REFRESH_RISK_MESSAGE)
    # Legacy monitor values are round-tripped but the desktop never starts HTTP.
    ids = set()
    fingerprints = set()
    for kind in ('courses', 'mutexes', 'delays'):
        local_ids = set()
        for index, entry in enumerate(getattr(config, kind)):
            path = '%s.%d' % (kind, index)
            if not isinstance(entry.id, str) or not entry.id.strip() or any(c in entry.id for c in ',\r\n[]\x00'):
                add(path + '.id', 'invalid_id', '标识不能为空或包含逗号、方括号及换行')
            elif entry.id in local_ids:
                add(path + '.id', 'duplicate_id', '标识重复')
            else:
                local_ids.add(entry.id)
        if kind == 'courses':
            ids = local_ids
    for index, course in enumerate(config.courses):
        path = 'courses.%d' % index
        for key in ('name', 'school'):
            value = getattr(course, key)
            if not isinstance(value, str) or not value.strip() or any(c in value for c in '\r\n\x00'):
                add(path + '.' + key, 'required', '请填写有效的课程名称' if key == 'name' else '请填写有效的开课单位')
        if type(course.class_no) is not int or course.class_no < 0:
            add(path + '.class_no', 'nonnegative_integer', '班号须为非负整数（允许 00）')
        if type(course.page) is not int or not 1 <= course.page <= 999:
            add(path + '.page', 'page_range', '选课页码须为 1 至 999 之间的整数')
        if course.identity not in ('bzx', 'bfx'):
            add(path + '.identity', 'choice', '请选择主修或辅修身份')
        fingerprint = (str(course.identity), str(course.name).strip(), str(course.class_no), str(course.school).strip())
        if fingerprint in fingerprints:
            add(path, 'duplicate_course', '同一身份下的相同课程、班号及开课单位已存在')
        fingerprints.add(fingerprint)
    if for_run and not config.courses:
        add('courses', 'required', '请添加至少一门目标课程')
    for index, rule in enumerate(config.mutexes):
        path = 'mutexes.%d.courses' % index
        if not isinstance(rule.courses, list) or any(not isinstance(c, str) for c in rule.courses):
            add(path, 'invalid_list', '请选择有效课程')
            continue
        if len(set(rule.courses)) < 2:
            add(path, 'minimum_two', '互斥组须包含至少两门不同课程')
        if len(set(rule.courses)) != len(rule.courses):
            add(path, 'duplicate_reference', '互斥组包含重复课程')
        if any(c not in ids for c in rule.courses):
            add(path, 'missing_course', '互斥组引用的课程已不存在')
    delayed = set()
    for index, rule in enumerate(config.delays):
        path = 'delays.%d' % index
        if not isinstance(rule.course, str) or rule.course not in ids:
            add(path + '.course', 'missing_course', '延迟规则引用的课程已不存在')
        elif rule.course in delayed:
            add(path + '.course', 'duplicate_delay', '每门课程只能设置一条延迟规则')
        else:
            delayed.add(rule.course)
        if type(rule.threshold) is not int or rule.threshold <= 0:
            add(path + '.threshold', 'positive_integer', '名额阈值须为正整数')
    return issues
