"""Config and credential transaction with the settings pointer as commit point.

New encrypted blobs precede settings publication; old blobs are removed only
after commit. A crash can leave an unreferenced encrypted blob, never settings
pointing at a blob which has not yet been written. The next successful load
reclaims unreferenced blobs.
"""
import hashlib
import json
import os
import re
from uuid import uuid4

from ..domain.config import AppConfig, validate
from .config_store import ConfigStore, atomic_write
from .credentials import _dpapi
from .portable import PortablePaths


def _can_remember():
    return os.name == 'nt'


def _protect(data):
    return _dpapi(data)


def _unprotect(data):
    return _dpapi(data, decrypt=True)


def _account(config):
    identity = [config.user.get('student_id', '').strip()]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode('utf-8')).hexdigest()


def _valid_ref(ref):
    return isinstance(ref, str) and re.fullmatch(r'credentials\.[0-9a-f]{32}\.dpapi', ref) is not None


class ConfigService:
    def __init__(self, paths, session_only=False):
        self.paths = paths if isinstance(paths, PortablePaths) else PortablePaths(paths)
        self.store = ConfigStore(self.paths)
        self._password = ''
        self._account = None
        self.cleanup_pending = False
        self.session_only = session_only

    def __repr__(self):
        return 'ConfigService()'

    def load(self):
        if not self.paths.data.exists():
            return self.store.load()
        from .config_store import _exclusive_lock
        # The transaction lock distinguishes orphaned crash debris from files
        # which another instance is currently staging.
        with _exclusive_lock(self.paths.data / 'credentials.lock'):
            config = self.store.load()
            self.cleanup_pending = False
            try:
                self._cleanup(config)
            except OSError:
                self.cleanup_pending = True
            return config

    def remembers(self, config):
        if self.session_only:
            return False
        return bool(config.extra_json.get('remember_password') and _valid_ref(config.extra_json.get('credential_ref')))

    def password_for(self, config):
        account = _account(config)
        if account == self._account:
            return self._password
        if not self.remembers(config) or not _can_remember():
            return ''
        path = self.paths.data / config.extra_json['credential_ref']
        try:
            raw = json.loads(_unprotect(path.read_bytes()).decode('utf-8'))
            if not isinstance(raw, dict) or raw.get('account') != account:
                return ''
            password = raw.get('password')
            if not isinstance(password, str):
                return ''
            return password
        except FileNotFoundError:
            return ''
        except (OSError, UnicodeError, ValueError):
            raise OSError('无法读取此账号保存的密码，请重新输入') from None

    def save(self, config, password='', remember=False):
        remember = remember and not self.session_only
        from .config_store import _exclusive_lock
        issues = validate(config)
        if issues:
            raise ValueError(issues[0].message)
        if remember and not _can_remember():
            raise RuntimeError('记住密码仅支持 Windows DPAPI；当前平台密码只保存在内存中')
        self.paths.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Serializes the entire staged-blob lifecycle, in addition to the
        # ConfigStore lock shared with direct config-only writers.
        with _exclusive_lock(self.paths.data / 'credentials.lock'):
            resolved_password = password or self.password_for(config)
            candidate = AppConfig.from_dict(config.to_dict())
            candidate.extra_json.pop('credential_ref', None)
            candidate.extra_json['remember_password'] = bool(remember and resolved_password)
            staged = None
            if remember and resolved_password:
                reference = 'credentials.%s.dpapi' % uuid4().hex
                staged = self.paths.data / reference
                payload = json.dumps({'account': _account(candidate), 'password': resolved_password}, ensure_ascii=False).encode('utf-8')
                atomic_write(staged, _protect(payload))
                candidate.extra_json['credential_ref'] = reference
            try:
                saved = self.store.save(candidate)
            except BaseException:
                if staged is not None:
                    try:
                        staged.unlink(missing_ok=True)
                    except OSError:
                        self.cleanup_pending = True
                raise
            self._password = resolved_password
            self._account = _account(saved)
            self.cleanup_pending = False
            try:
                self._cleanup(saved)
            except OSError:
                # The commit succeeded. Expose cleanup status without telling
                # the caller that configuration save failed after publication.
                self.cleanup_pending = True
            return saved

    def _cleanup(self, config):
        keep = config.extra_json.get('credential_ref')
        for path in self.paths.data.glob('credentials.*.dpapi'):
            if _valid_ref(path.name) and path.name != keep:
                path.unlink(missing_ok=True)
        self.paths.credentials.unlink(missing_ok=True)
        # Backups restore settings, never old remembered passwords.
        for index in (1, 2, 3):
            path = self.paths.data / ('settings.json.bak.%d' % index)
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError):
                continue
            if not isinstance(raw, dict) or 'credential_ref' not in raw:
                continue
            raw.pop('credential_ref', None)
            raw['remember_password'] = False
            atomic_write(path, (json.dumps(raw, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))

    def forget_password(self, config):
        saved = self.save(config, remember=False)
        self._password = ''
        self._account = None
        return saved
