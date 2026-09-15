"""Small allowlisted JS API. No HTTP, arbitrary paths or Python evaluation."""
from collections import deque
from dataclasses import asdict
import copy
import json
import os
import shutil
import threading
import time
from urllib.parse import unquote

from .adapters.config_service import ConfigService
from .adapters.ini_codec import import_ini, export_ini
from .domain.config import AppConfig, validate
from .domain.fields import CLIENT_FIELDS
from .runtime.supervisor import EngineSupervisor
from .runtime.journal import RollingLogWriter


class DesktopBridge:
    def __init__(self, paths, supervisor=None):
        self._paths = paths
        self._service = ConfigService(paths, session_only=True)
        self._supervisor = supervisor or EngineSupervisor(paths.data)
        self._mutation = threading.RLock()
        self._state_lock = threading.RLock()
        self._state = 'idle'
        self._snapshot = {'courses': []}
        self._logs = deque(maxlen=2000)
        self._log_sequence = 0
        self._generation = 0
        self._dirty = False
        self._closing = False
        self._window = None
        self._journal = RollingLogWriter(paths.logs)
        self._supervisor.state_changed.connect(self._on_state)
        self._supervisor.snapshot_received.connect(self._on_snapshot)
        self._supervisor.log_received.connect(self._on_log)

    def _on_state(self, state):
        with self._state_lock:
            self._state = state

    def _on_snapshot(self, snapshot):
        with self._state_lock:
            self._snapshot = {**copy.deepcopy(snapshot), 'received_at': time.time()}

    def _on_log(self, message):
        # Worker already curates/redacts logs. Bound storage before JS reads it.
        with self._state_lock:
            text = time.strftime('%m-%d %H:%M:%S') + '  ' + str(message).replace('\r', ' ').replace('\n', ' ')[:2000]
            self._log_sequence += 1
            self._logs.append((self._log_sequence, text))
        self._journal.submit(text)  # Disk latency never blocks the state/IPC reader.

    @staticmethod
    def _parse(raw):
        if len(json.dumps(raw, ensure_ascii=False)) > 256_000:
            raise ValueError('配置内容过大，请减少课程或规则数量')
        return AppConfig.from_dict(raw)

    @staticmethod
    def _error(error):
        if isinstance(error, (ValueError, RuntimeError)):
            return {'ok': False, 'error': str(error)}
        if isinstance(error, OSError):
            return {'ok': False, 'error': '无法读写本地数据，请检查软件目录权限和磁盘空间'}
        return {'ok': False, 'error': '操作未完成，请重新打开程序后重试'}

    def bootstrap(self):
        with self._mutation:
            try:
                config = self._service.load()
                fields = [{'key': f.key, 'label': f.label, 'help': f.help, 'default': f.default,
                           'type': f.type.__name__, 'level': f.level, 'min': f.min_value, 'max': f.max_value}
                          for f in CLIENT_FIELDS if not f.key.startswith('debug_') and f.level != 'compatibility']
                return {'ok': True, 'config': config.to_dict(), 'fields': fields,
                        'capabilities': {'incremental_logs': True},
                        'remembered': self._service.remembers(config)}
            except Exception as error:
                return self._error(error)

    def _save(self, raw, password, remember, for_run):
        self._ensure_open()
        config = self._parse(raw)
        if not isinstance(password, str) or len(password) > 4096 or type(remember) is not bool:
            raise ValueError('密码参数格式不正确')
        resolved = password or self._service.password_for(config)
        issues = validate(config, for_run=for_run, password=resolved)
        if issues:
            return {'ok': False, 'issues': [asdict(issue) for issue in issues]}
        saved = self._service.save(config, password=password, remember=remember)
        with self._state_lock:
            self._dirty = False
        return {'ok': True, 'config': saved.to_dict(), 'remembered': self._service.remembers(saved)}

    def save(self, config, password='', remember=False):
        with self._mutation:
            try:
                return self._save(config, password, remember, False)
            except Exception as error:
                return self._error(error)

    def start(self, config, password='', remember=False):
        with self._mutation:
            committed = None
            try:
                if self._supervisor.is_active:
                    raise ValueError('当前任务尚未停止')
                result = self._save(config, password, remember, True)
                if not result['ok']:
                    return result
                committed = result
                saved = AppConfig.from_dict(result['config'])
                with self._state_lock:
                    self._snapshot = {'courses': []}
                    self._logs.clear()
                    self._log_sequence = 0
                    self._generation += 1
                self._supervisor.start(saved.to_dict(), self._service.password_for(saved))
                return result
            except Exception as error:
                response = self._error(error)
                if committed is not None:
                    # Launch failure does not roll back an already published
                    # configuration. Return its revision so the UI can retry
                    # without overwriting newer edits or getting stuck stale.
                    response.update(committed=True, config=committed['config'],
                                    remembered=committed['remembered'])
                return response

    def stop(self):
        with self._mutation:
            try:
                self._ensure_open()
                self._supervisor.stop()
                return {'ok': True}
            except Exception as error:
                return self._error(error)

    def poll(self, cursor=None, generation=None):
        with self._state_lock:
            result = {'ok': True, 'state': self._state, 'snapshot': copy.deepcopy(self._snapshot),
                      'generation': self._generation, 'log_total': self._log_sequence,
                      'log_storage': self._journal.status()}
            if cursor is None:  # Compatible with older windows and explicit restart checks.
                result['logs'] = [text for _, text in self._logs]
            else:
                if type(cursor) is not int or cursor < 0:
                    return {'ok': False, 'error': '日志游标格式不正确'}
                first = self._logs[0][0] if self._logs else self._log_sequence + 1
                reset = generation != self._generation or cursor < first - 1 or cursor > self._log_sequence
                entries = (list(self._logs)[-500:] if reset else [] if cursor == self._log_sequence
                           else [(sid, text) for sid, text in self._logs if sid > cursor])
                entries = entries[:200]
                result.update(logs=[text for _, text in entries], logs_reset=reset,
                              log_cursor=entries[-1][0] if entries else self._log_sequence,
                              logs_more=bool(entries and entries[-1][0] < self._log_sequence))
            return result

    def set_dirty(self, dirty):
        with self._state_lock:
            self._dirty = bool(dirty)
        return {'ok': True}

    def import_config(self):
        # Paths are picked by the native dialog, never supplied by JS.
        if self._window is None:
            return {'ok': False, 'error': '文件窗口尚未就绪'}
        with self._mutation:
            try:
                self._ensure_open()
                import webview
                selected = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=False,
                                                           file_types=('INI 配置 (*.ini)',))
                if not selected:
                    return {'ok': True, 'canceled': True}
                config, password = import_ini(selected[0])
                return {'ok': True, 'config': config.to_dict(), 'password': password}
            except Exception as error:
                return self._error(error)

    def export_config(self, raw):
        if self._window is None:
            return {'ok': False, 'error': '文件窗口尚未就绪'}
        with self._mutation:
            try:
                self._ensure_open()
                config = self._parse(raw)
                issues = validate(config)
                if issues:
                    return {'ok': False, 'issues': [asdict(i) for i in issues], 'error': issues[0].message}
                import webview
                selected = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename='config.ini',
                                                           file_types=('INI 配置 (*.ini)',))
                if not selected:
                    return {'ok': True, 'canceled': True}
                target = selected[0] if isinstance(selected, (list, tuple)) else selected
                export_ini(config, target)
                return {'ok': True}
            except Exception as error:
                return self._error(error)

    def open_external_link(self, url):
        """Open one of the fixed documentation links outside the privileged WebView."""
        allowed = {
            'https://github.com/zhongxinghong/PKUAutoElective#自定义选课规则':
                'https://github.com/zhongxinghong/PKUAutoElective#%E8%87%AA%E5%AE%9A%E4%B9%89%E9%80%89%E8%AF%BE%E8%A7%84%E5%88%99',
            'https://github.com/Aerisun': 'https://github.com/Aerisun',
            'mailto:ywbforpureuse@gmail.com': 'mailto:ywbforpureuse@gmail.com',
        }
        try:
            self._ensure_open()
            target = allowed.get(unquote(url)) if isinstance(url, str) else None
            if target is None:
                return {'ok': False, 'error': '不允许打开此链接'}
            os.startfile(target)
            return {'ok': True}
        except Exception:
            return {'ok': False, 'error': '无法打开链接，请检查系统默认浏览器或邮箱应用'}

    def clear_data(self):
        with self._mutation:
            try:
                self._ensure_open()
                if self._supervisor.is_active:
                    raise ValueError('请先停止运行，再清除本地数据')
                recover = getattr(self._supervisor, 'recover_power', None)
                if recover:
                    recover()  # Never erase the only rollback journal after a restore failure.
                target = self._paths.data
                if target.is_symlink() or target.resolve() != self._paths.root / 'data':
                    raise ValueError('数据目录位置异常，未执行清除')
                if not self._journal.close():
                    raise ValueError('日志仍在写入，请稍后重试清除数据')
                # Chromium holds its own profile open until the window exits.
                # Mark it for deferred removal; all other owned data is removed now.
                if target.exists():
                    for child in target.iterdir():
                        if child.name == 'cache' and self._window is not None:
                            continue
                        if child.is_dir() and not child.is_symlink():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
                self._clear_profile_on_exit = True
                self._paths.initialize_environment()
                self._service = ConfigService(self._paths, session_only=True)
                self._journal = RollingLogWriter(self._paths.logs)
                with self._state_lock:
                    self._dirty = False
                    self._snapshot = {'courses': []}
                    self._logs.clear()
                    self._log_sequence = 0
                    self._state = 'idle'
                    self._generation += 1
                return {'ok': True, 'config': AppConfig().to_dict(),
                        'cache_pending_exit': self._window is not None}
            except Exception as error:
                return self._error(error)

    def _ensure_open(self):
        if self._closing:
            raise ValueError('工作台正在退出')

    def _shutdown(self):
        with self._mutation:
            self._closing = True
            if not self._supervisor.shutdown(timeout_ms=6000):
                self._closing = False
                return False
            if not self._journal.close():
                self._closing = False
                return False
            return True
