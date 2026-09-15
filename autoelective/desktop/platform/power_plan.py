"""Recoverable, task-scoped Windows 10/11 power scheme (no service or startup task).

Execution requests cannot override lid-close sleep. Duplicate the user's scheme,
change only the duplicate, verify both AC/DC, and keep the original for rollback.
The supervisor owns this lease, so killing a stuck worker still restores power.
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import uuid


BUTTONS = '4f971e89-eebd-4455-a8de-9e59040e7347'
SLEEP = '238c9fa8-0aad-41ed-83f4-97be242c8f20'
VIDEO = '7516b95f-f776-4464-8c53-06167f40cc99'
POWER_BUTTON = '7648efa3-dd9c-4e3e-b566-50f929386280'
SETTINGS = (
    (BUTTONS, '5ca83367-6e45-459f-a27b-476b1d01c936', 0),  # LIDACTION
    (BUTTONS, '96996bc0-ad50-47ec-923b-6f41874dd9eb', 0),  # sleep button
    (BUTTONS, POWER_BUTTON, 0),  # Preserve an existing shutdown action (3).
    (SLEEP, '29f6c1db-86da-48c5-9fdb-f2b67b1f44da', 0),  # STANDBYIDLE
    (SLEEP, '9d7815a6-7ee4-497e-8888-515a05f02364', 0),  # HIBERNATEIDLE
    (SLEEP, '7bc4a2f9-d8fc-4469-b07b-33eb785aaca0', 0),  # unattended sleep
    (SLEEP, '94ac6d29-73ce-41a6-809f-6363ba21b47e', 0),  # hybrid sleep
    (SLEEP, 'abfc2519-3608-4c2a-94ea-171b0ed546ab', 0),  # S1-S3 standby
    (SLEEP, 'a4b195f5-8225-47d8-8012-9d41369786e2', 1),  # honor system requests
    (VIDEO, '3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e', 0),  # display timeout
    (VIDEO, '8ec4b3a5-6868-48c2-be75-4f3044be88a7', 0),  # locked display timeout
)
SETUP_ERROR = ('无法启用合盖持续运行保护，任务尚未启动。请右键程序选择“以管理员身份运行”后重试；'
               '若电脑受单位电源策略管理，请联系管理员允许合盖不睡眠和关闭自动睡眠。')
RESTORE_ERROR = ('未能恢复原电源方案。请保留软件 data 文件夹并重新打开程序重试，'
                 '或在 Windows“电源选项”中选择原方案。')


def target_value(setting, requested, current):
    return 3 if setting == POWER_BUTTON and current == 3 else requested


class GUID(ctypes.Structure):
    _fields_ = [('a', ctypes.c_uint32), ('b', ctypes.c_uint16),
                ('c', ctypes.c_uint16), ('d', ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)

    def text(self):
        return str(uuid.UUID(bytes_le=bytes(self)))


class WindowsPowerApi:
    """Use Win32 status codes and GUIDs, independent of Windows display language."""
    def __init__(self):
        self.dll = ctypes.WinDLL('powrprof', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        pointer = ctypes.POINTER(GUID)
        signatures = {
            'PowerGetActiveScheme': [wintypes.HKEY, ctypes.POINTER(pointer)],
            'PowerDuplicateScheme': [wintypes.HKEY, pointer, ctypes.POINTER(pointer)],
            'PowerSetActiveScheme': [wintypes.HKEY, pointer],
            'PowerDeleteScheme': [wintypes.HKEY, pointer],
            'PowerSettingAccessCheck': [ctypes.c_int, pointer],
            'PowerWriteFriendlyName': [wintypes.HKEY, pointer, pointer, pointer,
                                       ctypes.c_void_p, wintypes.DWORD],
        }
        for source in ('AC', 'DC'):
            signatures['PowerRead%sValueIndex' % source] = [
                wintypes.HKEY, pointer, pointer, pointer, ctypes.POINTER(wintypes.DWORD)]
            signatures['PowerWrite%sValueIndex' % source] = [
                wintypes.HKEY, pointer, pointer, pointer, wintypes.DWORD]
        for name, arguments in signatures.items():
            function = getattr(self.dll, name)
            function.argtypes, function.restype = arguments, wintypes.DWORD
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p

    @staticmethod
    def check(code):
        if code:
            raise ctypes.WinError(code)

    def active(self):
        value = ctypes.POINTER(GUID)()
        self.check(self.dll.PowerGetActiveScheme(None, ctypes.byref(value)))
        try:
            return value.contents.text()
        finally:
            self.kernel.LocalFree(value)

    def duplicate(self, original, destination):
        value = GUID.parse(destination)
        pointer = ctypes.pointer(value)
        self.check(self.dll.PowerDuplicateScheme(None, ctypes.byref(GUID.parse(original)),
                                                 ctypes.byref(pointer)))
        if pointer.contents.text() != destination:
            raise OSError('Unexpected power scheme identifier')

    def name(self, scheme):
        label = ctypes.create_unicode_buffer('PKUCourseHelper · 选课运行保护')
        self.check(self.dll.PowerWriteFriendlyName(None, ctypes.byref(GUID.parse(scheme)),
                                                   None, None, label, ctypes.sizeof(label)))

    def activate(self, scheme):
        self.check(self.dll.PowerSetActiveScheme(None, ctypes.byref(GUID.parse(scheme))))

    def delete(self, scheme):
        result = self.dll.PowerDeleteScheme(None, ctypes.byref(GUID.parse(scheme)))
        if result != 2:  # Recovery also handles a crash before the duplicate existed.
            self.check(result)

    def read(self, scheme, subgroup, setting, source):
        value = wintypes.DWORD()
        self.check(getattr(self.dll, 'PowerRead%sValueIndex' % source)(
            None, ctypes.byref(GUID.parse(scheme)), ctypes.byref(GUID.parse(subgroup)),
            ctypes.byref(GUID.parse(setting)), ctypes.byref(value)))
        return value.value

    def write(self, scheme, subgroup, setting, source, value):
        self.check(getattr(self.dll, 'PowerWrite%sValueIndex' % source)(
            None, ctypes.byref(GUID.parse(scheme)), ctypes.byref(GUID.parse(subgroup)),
            ctypes.byref(GUID.parse(setting)), value))

    def check_policy(self):
        # A successful plan read alone does not prove group policy permits it.
        for accessor in (19, 20):
            self.check(self.dll.PowerSettingAccessCheck(accessor, None))
        for _, setting, _ in SETTINGS:
            for accessor in (0, 1):
                self.check(self.dll.PowerSettingAccessCheck(accessor, ctypes.byref(GUID.parse(setting))))


def machine_key():
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                       0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        identity = winreg.QueryValueEx(key, 'MachineGuid')[0]
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]


class PowerPlanLease:
    def __init__(self, data_root, api=None, machine=None):
        self.path = Path(data_root) / ('power-recovery-%s.json' % (machine or machine_key()))
        self.api = api or WindowsPowerApi()
        self.record = None
        self.ready = False
        self.error = ''

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(self.record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def recover(self):
        if not self.path.exists():
            return
        try:
            record = json.loads(self.path.read_text(encoding='utf-8'))
            if record.get('version') != 1:
                raise ValueError('Unknown recovery format')
            original, owned = (str(uuid.UUID(record[key])) for key in ('original', 'owned'))
            if original == owned:
                raise ValueError('Invalid recovery scheme')
            self.record = dict(version=1, original=original, owned=owned)
            self.close()
        except Exception as error:
            raise RuntimeError(RESTORE_ERROR) from error

    def acquire(self):
        try:
            self.recover()
            self.api.check_policy()
            self.record = dict(version=1, original=self.api.active(), owned=str(uuid.uuid4()))
            # Commit recovery BEFORE creating or activating a scheme.
            self._save()
            self.api.duplicate(self.record['original'], self.record['owned'])
            self.api.name(self.record['owned'])
            self.ensure()
        except Exception as error:
            try:
                self.close()
            except Exception:
                raise RuntimeError(SETUP_ERROR + ' ' + RESTORE_ERROR) from error
            raise RuntimeError(SETUP_ERROR) from error

    def ensure(self):
        self.ready = False
        try:
            self.api.check_policy()
            owned = self.record['owned']
            active = self.api.active()
            if active != owned and active != self.record['original']:
                # Restore the latest external selection after this task ends.
                self.record['original'] = active
                self._save()
            changed = False
            for subgroup, setting, requested in SETTINGS:
                for source in ('AC', 'DC'):
                    current = self.api.read(owned, subgroup, setting, source)
                    value = target_value(setting, requested, current)
                    if current != value:
                        self.api.write(owned, subgroup, setting, source, value)
                        changed = True
            if changed or active != owned:
                self.api.activate(owned)
            verified = all((current := self.api.read(owned, group, setting, source)) ==
                           target_value(setting, requested, current)
                           for group, setting, requested in SETTINGS for source in ('AC', 'DC'))
            if self.api.active() != owned or not verified:
                raise OSError('Power plan verification failed')
            self.ready, self.error = True, ''
        except Exception:
            self.error = '合盖运行保护暂时失效，正在重试；请保持开盖并检查系统电源策略。'
            raise

    def close(self):
        self.ready = False
        if self.record is None:
            return
        try:
            owned, original = self.record['owned'], self.record['original']
            if self.api.active() == owned:
                self.api.activate(original)
                if self.api.active() != original:
                    raise OSError('Restore verification failed')
            self.api.delete(owned)
            self.path.unlink(missing_ok=True)
            self.record, self.error = None, ''
        except Exception as error:
            self.error = RESTORE_ERROR
            raise RuntimeError(RESTORE_ERROR) from error
