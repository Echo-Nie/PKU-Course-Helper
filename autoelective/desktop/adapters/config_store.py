import json
import hashlib
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ..domain.config import AppConfig, validate


class RevisionConflict(ValueError):
    pass


def atomic_write(path, content):
    """Same-directory replace. Failed writes never truncate the previous file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


@contextmanager
def _exclusive_lock(path):
    with open(path, 'a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            if stream.read(1) == b'':
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RevisionConflict('配置正在被其他进程保存，请稍后重试') from None
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RevisionConflict('配置正在被其他进程保存，请稍后重试') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class ConfigStore:
    def __init__(self, paths):
        self.paths = paths
        self._loaded = False
        self._digest = None

    def _read(self):
        if not self.paths.settings.exists():
            return AppConfig(), None
        try:
            content = self.paths.settings.read_bytes()
            raw = json.loads(content.decode('utf-8'))
            config = AppConfig.from_dict(raw)
            issues = validate(config)
            if issues:
                raise ValueError('配置字段 %s：%s；原文件已保留' % (issues[0].field_path, issues[0].message))
            return config, hashlib.sha256(content).digest()
        except (json.JSONDecodeError, UnicodeError):
            raise ValueError('配置文件损坏，原文件已保留；可从备份恢复') from None

    def load(self):
        config, self._digest = self._read()
        self._loaded = True
        return config

    def save(self, config):
        issues = validate(config)
        if issues:
            raise ValueError(issues[0].message)
        self.paths.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        with _exclusive_lock(self.paths.data / 'settings.lock'):
            current, digest = self._read()
            if current.revision != config.revision or (self._loaded and digest != self._digest):
                raise RevisionConflict('配置已在其他窗口修改，请重新加载后保存')
            saved = AppConfig.from_dict(config.to_dict())
            saved.revision += 1
            payload = (json.dumps(saved.to_dict(), ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
            if self.paths.settings.exists():
                # Backups contain configuration only; credentials are never in JSON.
                for index in (3, 2):
                    previous = self.paths.data / ('settings.json.bak.%d' % (index - 1))
                    if previous.exists():
                        shutil.copyfile(previous, self.paths.data / ('settings.json.bak.%d' % index))
                atomic_write(self.paths.data / 'settings.json.bak.1', self.paths.settings.read_bytes())
            atomic_write(self.paths.settings, payload)
            self._digest = hashlib.sha256(payload).digest()
            self._loaded = True
            return saved
