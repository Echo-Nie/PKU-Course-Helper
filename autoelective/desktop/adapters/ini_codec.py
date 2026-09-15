import configparser
import io
import re

from ..domain.config import AppConfig, CourseConfig, DelayRule, MutexRule
from ..domain.fields import CLIENT_FIELDS
from .config_store import atomic_write


def import_ini(path):
    parser = configparser.RawConfigParser()
    try:
        with open(path, encoding='utf-8-sig') as stream:
            parser.read_file(stream)
        config = AppConfig()
        password = parser.get('user', 'password', fallback='')
        known = {}
        def take(section, key, kind, default):
            known.setdefault(section, set()).add(key)
            if kind is bool:
                return parser.getboolean(section, key, fallback=default)
            if kind is int:
                return parser.getint(section, key, fallback=default)
            if kind is float:
                return parser.getfloat(section, key, fallback=default)
            return parser.get(section, key, fallback=default)
        for key, default in config.user.items():
            config.user[key] = take('user', key, type(default), default)
        legacy_identity = take('user', 'identity', str, 'bzx')
        take('user', 'dual_degree', bool, False)
        known.setdefault('user', set()).add('password')
        for spec in CLIENT_FIELDS:
            config.client[spec.key] = take('client', spec.key, spec.type, spec.default)
        for key, default in config.monitor.items():
            config.monitor[key] = take('monitor', key, type(default), default)
        for section in parser.sections():
            match = re.fullmatch(r'\s*(course|mutex|delay)\s*:\s*([^,]+?)\s*', section)
            if not match:
                continue
            kind, identifier = match.groups()
            if kind == 'course':
                config.courses.append(CourseConfig(id=identifier, name=take(section, 'name', str, ''), class_no=take(section, 'class', int, 1), school=take(section, 'school', str, ''), page=take(section, 'page', int, config.client['supply_cancel_page']), identity=take(section, 'identity', str, legacy_identity)))
                category = take(section, 'ui_category', str, '')
                if category in ('major', 'elective', 'minor'):
                    config.extra_json.setdefault('course_categories', {})[identifier] = category
            elif kind == 'mutex':
                config.mutexes.append(MutexRule(id=identifier, courses=[s.strip() for s in take(section, 'courses', str, '').split(',') if s.strip()]))
            else:
                config.delays.append(DelayRule(id=identifier, course=take(section, 'course', str, ''), threshold=take(section, 'threshold', int, 1)))
            # Normalize section spelling so unknown keys survive canonical export.
            canonical = kind + ':' + identifier
            extras = {k: v for k, v in parser.items(section) if k not in known.get(section, set()) and k.lower() != 'password'}
            if extras:
                config.extra_ini[canonical] = extras
        for section in parser.sections():
            if re.fullmatch(r'\s*(course|mutex|delay)\s*:\s*([^,]+?)\s*', section):
                continue
            extra = {k: v for k, v in parser.items(section) if k not in known.get(section, set()) and k.lower() != 'password'}
            if extra:
                config.extra_ini[section] = extra
        config.client['print_mutex_rules'] = True
        return config, password
    except (configparser.Error, UnicodeError, ValueError):
        raise ValueError('INI 配置格式不正确，请检查节名称、数字及开关值') from None


def to_parser(config, password=''):
    parser = configparser.RawConfigParser()
    # Legacy network hooks still consult these user keys. Desktop scheduling
    # never uses them; it selects the identity on each individual course.
    sections = [('user', {'dual_degree': False, 'identity': 'bzx', **config.user, 'password': password}), ('client', {**config.client, 'print_mutex_rules': True}), ('monitor', config.monitor)]
    sections.extend(('course:' + c.id, {'name': c.name, 'class': c.class_no, 'school': c.school, 'page': c.page, 'identity': c.identity}) for c in config.courses)
    categories = config.extra_json.get('course_categories', {})
    if isinstance(categories, dict):
        for section, values in sections:
            category = categories.get(section.removeprefix('course:')) if section.startswith('course:') else None
            if category in ('major', 'elective', 'minor'):
                values['ui_category'] = category
    sections.extend(('mutex:' + m.id, {'courses': ','.join(m.courses)}) for m in config.mutexes)
    sections.extend(('delay:' + d.id, {'course': d.course, 'threshold': d.threshold}) for d in config.delays)
    for section, values in sections:
        parser.add_section(section)
        merged = {**config.extra_ini.get(section, {}), **values}
        for key, value in merged.items():
            if key.lower() == 'password' and section != 'user':
                continue
            parser.set(section, key, str(value).lower() if isinstance(value, bool) else str(value))
    for section, values in config.extra_ini.items():
        # Deleted courses/rules must not be recreated from preserved unknown keys.
        if parser.has_section(section) or section.startswith(('course:', 'mutex:', 'delay:')):
            continue
        parser.add_section(section)
        for key, value in values.items():
            if key.lower() != 'password':
                parser.set(section, key, str(value))
    return parser


def export_ini(config, path, password=None):
    output = io.StringIO()
    to_parser(config, password=password or '').write(output)
    atomic_write(path, output.getvalue().encode('utf-8'))
