import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PortablePaths:
    root: Path

    def __post_init__(self):
        object.__setattr__(self, 'root', Path(self.root).resolve())

    @classmethod
    def discover(cls):
        if getattr(sys, 'frozen', False):
            return cls(Path(sys.executable).parent)
        return cls(Path(__file__).resolve().parents[3])

    @property
    def data(self):
        return self.root / 'data'

    @property
    def settings(self):
        return self.data / 'settings.json'

    @property
    def credentials(self):
        return self.data / 'credentials.dpapi'

    @property
    def logs(self):
        return self.data / 'logs'

    @property
    def cache(self):
        return self.data / 'cache'

    @property
    def tmp(self):
        return self.data / 'tmp'

    def initialize_environment(self):
        for path in (self.data, self.logs, self.cache, self.tmp):
            if path.is_symlink() or self.root not in path.resolve().parents:
                raise ValueError('数据目录包含外部链接，请使用完整解压的独立软件文件夹')
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
        for key in ('TEMP', 'TMP', 'TMPDIR'):
            os.environ[key] = str(self.tmp)
        for key in ('XDG_CACHE_HOME', 'MPLCONFIGDIR', 'TFHUB_CACHE', 'NUMBA_CACHE_DIR'):
            os.environ[key] = str(self.cache)
        os.environ['XDG_CONFIG_HOME'] = str(self.data)
        os.environ['XDG_DATA_HOME'] = str(self.data)
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        sys.dont_write_bytecode = True
        # tempfile may have been imported before this adapter by the launcher.
        import tempfile
        tempfile.tempdir = str(self.tmp)
        return self
