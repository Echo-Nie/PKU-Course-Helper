import copy
import json
import os
import uuid

import pytest

from autoelective.desktop.platform.power_plan import (
    PowerPlanLease, WindowsPowerApi, SETTINGS, POWER_BUTTON, target_value,
)


class FakePowerApi:
    def __init__(self):
        self.original = str(uuid.uuid4())
        self.selected = self.original
        self.plans = {self.original: {(group, setting, source): 1
                       for group, setting, _ in SETTINGS for source in ('AC', 'DC')}}
        self.calls = []
        self.denied = False
        self.fail_write = False
        self.fail_restore = False
        self.ignore_activation = False

    def active(self): return self.selected
    def check_policy(self):
        if self.denied: raise PermissionError('private policy detail')
    def duplicate(self, original, destination):
        self.calls.append(('duplicate', destination))
        self.plans[destination] = self.plans[original].copy()
    def name(self, scheme): pass
    def activate(self, scheme):
        if self.fail_restore and scheme == self.original:
            raise PermissionError('private restore detail')
        if not self.ignore_activation:
            self.selected = scheme
        self.calls.append(('activate', scheme))
    def delete(self, scheme):
        assert scheme != self.selected
        self.plans.pop(scheme, None)
    def read(self, scheme, group, setting, source):
        return self.plans[scheme][group, setting, source]
    def write(self, scheme, group, setting, source, value):
        if self.fail_write: raise PermissionError('private write detail')
        self.plans[scheme][group, setting, source] = value
        self.calls.append(('write', scheme))


def test_both_power_sources_protected_and_original_preserved(tmp_path):
    api = FakePowerApi()
    original = copy.deepcopy(api.plans)
    lease = PowerPlanLease(tmp_path, api, 'test-machine')
    lease.acquire()
    assert lease.ready and lease.path.exists()
    for group, setting, expected in SETTINGS:
        for source in ('AC', 'DC'):
            assert api.read(api.selected, group, setting, source) == expected
    assert api.plans[api.original] == original[api.original]
    before = len(api.calls)
    for _ in range(1000): lease.ensure()
    assert len(api.calls) == before  # Healthy monitoring does not churn power settings.
    lease.close()
    lease.close()
    assert api.plans == original and api.selected == api.original
    assert not lease.path.exists()


@pytest.mark.parametrize('failure', ['denied', 'fail_write', 'ignore_activation'])
def test_setup_fails_closed_and_rolls_back_partial_changes(tmp_path, failure):
    api = FakePowerApi()
    setattr(api, failure, True)
    lease = PowerPlanLease(tmp_path, api, 'test-machine')
    with pytest.raises(RuntimeError, match='任务尚未启动') as caught:
        lease.acquire()
    assert 'private' not in str(caught.value)
    assert not lease.ready
    assert api.selected == api.original and list(api.plans) == [api.original]
    assert not lease.path.exists()


def test_crash_recovery_and_failed_restore_retain_recovery_evidence(tmp_path):
    api = FakePowerApi()
    lease = PowerPlanLease(tmp_path, api, 'test-machine')
    lease.acquire()
    api.fail_restore = True
    recovered = PowerPlanLease(tmp_path, api, 'test-machine')
    with pytest.raises(RuntimeError, match='原电源方案'): recovered.recover()
    assert lease.path.exists()
    api.fail_restore = False
    recovered.recover()
    assert api.selected == api.original and not lease.path.exists()


def test_journal_is_durable_before_duplicate_and_activation(tmp_path):
    api = FakePowerApi()
    lease = PowerPlanLease(tmp_path, api, 'test-machine')
    duplicate = api.duplicate
    def check(original, owned):
        record = json.loads(lease.path.read_text())
        assert record['original'] == original and record['owned'] == owned
        duplicate(original, owned)
    api.duplicate = check
    lease.acquire()
    lease.close()


def test_plan_switch_drift_and_policy_recovery(tmp_path):
    api = FakePowerApi()
    lease = PowerPlanLease(tmp_path, api, 'test-machine')
    lease.acquire()
    owned = api.selected
    other = str(uuid.uuid4())
    api.plans[other] = api.plans[api.original].copy()
    api.selected = other
    group, setting, _ = SETTINGS[0]
    api.plans[owned][group, setting, 'DC'] = 2
    lease.ensure()
    assert api.selected == owned and api.read(owned, group, setting, 'DC') == 0
    api.denied = True
    with pytest.raises(PermissionError): lease.ensure()
    assert not lease.ready and lease.error
    api.denied = False
    lease.ensure()
    assert lease.ready and not lease.error
    lease.close()
    assert api.selected == other  # Preserve the latest external scheme choice.


def test_external_plan_switch_at_stop_is_preserved(tmp_path):
    api = FakePowerApi()
    lease = PowerPlanLease(tmp_path, api, 'test-machine')
    lease.acquire()
    api.selected = api.original
    lease.close()
    assert api.selected == api.original


def test_existing_shutdown_button_and_critical_battery_settings_untouched(tmp_path):
    api = FakePowerApi()
    for group, setting, _ in SETTINGS:
        if setting == POWER_BUTTON:
            api.plans[api.original][group, setting, 'AC'] = 3
    sentinel = ('battery', 'critical-action', 'DC')
    api.plans[api.original][sentinel] = 2
    lease = PowerPlanLease(tmp_path, api, 'test-machine')
    lease.acquire()
    assert api.plans[api.selected][sentinel] == 2
    assert next(v for (g, s, p), v in api.plans[api.selected].items() if s == POWER_BUTTON and p == 'AC') == 3
    lease.close()


def test_portable_recovery_never_uses_another_computers_journal(tmp_path):
    api = FakePowerApi()
    lease = PowerPlanLease(tmp_path, api, 'computer-a')
    lease.acquire()
    owned = api.selected
    PowerPlanLease(tmp_path, api, 'computer-b').recover()
    assert api.selected == owned and lease.path.exists()
    lease.close()


@pytest.mark.skipif(os.name != 'nt' or os.environ.get('RUN_NATIVE_POWER_TESTS') != '1',
                    reason='Explicit opt-in: create, verify and delete an INACTIVE Windows scheme')
def test_native_windows_all_settings_roundtrip_without_activating_scheme():
    api = WindowsPowerApi()
    original, owned = api.active(), str(uuid.uuid4())
    created = False
    try:
        api.check_policy()
        api.duplicate(original, owned)
        created = True
        api.name(owned)
        for group, setting, requested in SETTINGS:
            for source in ('AC', 'DC'):
                value = target_value(setting, requested, api.read(owned, group, setting, source))
                api.write(owned, group, setting, source, value)
                assert api.read(owned, group, setting, source) == value
        assert api.active() == original
    finally:
        if created: api.delete(owned)
        assert api.active() == original
