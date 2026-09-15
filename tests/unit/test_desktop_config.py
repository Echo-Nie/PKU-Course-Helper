import math

import pytest

from autoelective.desktop.domain.config import AppConfig, CourseConfig, DelayRule, MutexRule, validate


def test_defaults_allow_draft_but_require_identity_and_courses_to_run():
    config = AppConfig()
    assert validate(config) == []
    assert {i.field_path for i in validate(config, for_run=True)} >= {'user.student_id', 'user.password', 'courses'}


def test_password_never_serialized_and_ids_survive_roundtrip():
    config = AppConfig(courses=[CourseConfig(name='数学', class_no=1, school='数学学院')])
    config.user['password'] = 'secret'
    decoded = AppConfig.from_dict(config.to_dict())
    assert decoded.courses[0].id == config.courses[0].id
    assert 'secret' not in str(config.to_dict())
    assert 'secret' not in repr(config)


def test_class_zero_survives_config_roundtrip_and_matches_school_class_00():
    from autoelective.course import Course

    config = AppConfig(courses=[CourseConfig(name='数学', class_no=0, school='数学学院')])
    config.user['student_id'] = 'test-student'
    decoded = AppConfig.from_dict(config.to_dict())
    assert decoded.courses[0].class_no == 0
    assert validate(decoded, for_run=True, password='test-password') == []
    course = decoded.courses[0]
    assert Course(course.name, course.class_no, course.school) == Course('数学', '00', '数学学院')


@pytest.mark.parametrize('class_no', [-1, 1.5, True, None, '', '00'])
def test_class_number_requires_nonnegative_integer_in_saved_config(class_no):
    config = AppConfig(courses=[CourseConfig(name='数学', class_no=class_no, school='数学学院')])
    assert any(i.field_path == 'courses.0.class_no' for i in validate(config))


@pytest.mark.parametrize('value', [math.inf, math.nan, -1, 'eight', True, 10 ** 1000])
def test_refresh_rejects_invalid_numbers(value):
    config = AppConfig()
    config.client['refresh_interval'] = value
    assert any(i.field_path == 'client.refresh_interval' for i in validate(config))


def test_minimum_actual_refresh_and_reference_integrity():
    config = AppConfig(courses=[CourseConfig(id='a', name='数学', school='数学学院')])
    config.client.update(refresh_interval=4, random_deviation=0.5)
    config.mutexes = [MutexRule(courses=['a', 'missing'])]
    config.delays = [DelayRule(course='missing', threshold=0)]
    codes = {i.code for i in validate(config)}
    assert {'refresh_floor', 'missing_course', 'positive_integer'} <= codes


def test_duplicate_courses_and_delay_rules():
    config = AppConfig(courses=[CourseConfig(id='a', name='数学', school='数学学院'), CourseConfig(id='b', name='数学', school='数学学院')])
    config.delays = [DelayRule(course='a'), DelayRule(course='a')]
    assert {'duplicate_course', 'duplicate_delay'} <= {i.code for i in validate(config)}


def test_unknown_json_fields_roundtrip_and_future_version_rejected():
    config = AppConfig.from_dict({'theme': {'accent': 'blue'}, 'user': {'password': 'secret'}})
    assert config.to_dict()['theme'] == {'accent': 'blue'}
    assert 'password' not in config.to_dict()['user']
    with pytest.raises(ValueError, match='版本'):
        AppConfig.from_dict({'schema_version': 999})


def test_legacy_monitor_fields_are_inert_and_preserved():
    config = AppConfig(monitor={'host': '0.0.0.0', 'port': 80})
    assert validate(config) == []
    assert AppConfig.from_dict(config.to_dict()).monitor == config.monitor


def test_new_rate_defaults_and_shared_pool_budget():
    config = AppConfig()
    assert config.client['refresh_interval'] == 6
    assert config.client['random_deviation'] == 0.2
    assert config.client['elective_client_pool_size'] == 4
    assert config.client['page_pool_size'] == 1
    assert validate(config) == []
    config.client['page_pool_size'] = 3
    assert validate(config) == []  # Legacy per-page quota is inert.


def test_json_legacy_courses_inherit_global_page_and_explicit_page_wins():
    config = AppConfig.from_dict({'client': {'supply_cancel_page': 4}, 'courses': [
        {'id': 'a', 'name': '数学', 'class_no': 1, 'school': '数院'},
        {'id': 'b', 'name': '物理', 'class_no': 1, 'school': '物院', 'page': 2},
    ]})
    assert [c.page for c in config.courses] == [4, 2]
    assert [c.page for c in AppConfig.from_dict(config.to_dict()).courses] == [4, 2]


@pytest.mark.parametrize('page', [0, -1, '1', True, 1000, 1.5])
def test_course_page_rejects_invalid_type_or_range(page):
    config = AppConfig(courses=[CourseConfig(name='数学', school='数院', page=page)])
    assert any(i.field_path == 'courses.0.page' for i in validate(config))


def test_page_999_is_valid_but_duplicate_course_across_pages_is_not():
    config = AppConfig(courses=[CourseConfig(name='数学', school='数院', page=999)])
    assert validate(config) == []
    config.courses.append(CourseConfig(name='数学', school='数院', page=1))
    assert any(i.code == 'duplicate_course' for i in validate(config))


def test_three_second_floor_warns_about_frequency_risk():
    config = AppConfig()
    config.client.update(refresh_interval=3, random_deviation=0.1)
    issue = next(i for i in validate(config) if i.code == 'refresh_floor')
    assert '3 秒' in issue.message and '频繁' in issue.message


def test_direct_interval_below_three_explains_frequency_risk():
    config = AppConfig()
    config.client.update(refresh_interval=2, random_deviation=0)
    assert any(i.code == 'refresh_floor' and '频繁' in i.message for i in validate(config))


def test_fixed_course_pages_are_not_blocked_by_hidden_legacy_global():
    config = AppConfig.from_dict({'client': {'supply_cancel_page': 0}, 'courses': [
        {'name': '数学', 'school': '数院', 'page': 2},
    ]})
    assert validate(config) == []


@pytest.mark.parametrize('size', [0, 6, True, 1.1, '2'])
def test_legacy_page_pool_size_does_not_block_automatic_allocation(size):
    config = AppConfig()
    config.client['page_pool_size'] = size
    assert not any(i.field_path == 'client.page_pool_size' for i in validate(config))


def test_per_course_identity_migrates_global_and_overrides_it():
    config = AppConfig.from_dict({'user': {'student_id': '123', 'identity': 'bfx', 'dual_degree': True},
                                 'client': {'print_mutex_rules': False},
                                 'courses': [{'name': '数学', 'school': '数院'},
                                             {'name': '物理', 'school': '物院', 'identity': 'bzx'}]})
    assert config.user == {'student_id': '123'}
    assert [c.identity for c in config.courses] == ['bfx', 'bzx']
    assert config.client['print_mutex_rules'] is True
    assert validate(config) == []


def test_same_course_in_two_identities_is_distinct():
    config = AppConfig(courses=[CourseConfig(name='数学', school='数院', identity=identity)
                                for identity in ('bzx', 'bfx')])
    assert validate(config) == []
    config.courses[1].identity = 'unknown'
    assert any(i.field_path == 'courses.1.identity' for i in validate(config))
