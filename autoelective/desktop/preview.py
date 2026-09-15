"""Offline native UI check using disposable data, never school credentials."""
import os
from pathlib import Path
import shutil
import sys
import tempfile

from .bridge import DesktopBridge


class PreviewBridge(DesktopBridge):
    def bootstrap(self):
        return {**super().bootstrap(), 'preview': True}

    def start(self, *args, **kwargs):
        return {'ok': False, 'error': '离线预览不会登录或选课，请正常启动程序后使用。'}

    def import_config(self):
        return {'ok': False, 'error': '离线预览不导入个人配置。'}


def run_preview():
    from . import app
    from .platform import instance
    from .adapters.portable import PortablePaths
    from .adapters.config_service import ConfigService
    from .domain.config import AppConfig, CourseConfig

    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
    # Share neither data nor a lifetime lock with the user's live application.
    profile = Path(tempfile.mkdtemp(prefix='.ui-preview-', dir=root))
    paths = PortablePaths(profile).initialize_environment()
    if not getattr(sys, 'frozen', False):
        (profile / 'frontend' / 'dist').mkdir(parents=True)
        shutil.copy2(root / 'frontend' / 'dist' / 'index.html', profile / 'frontend' / 'dist' / 'index.html')
    config = AppConfig(courses=[
        CourseConfig(id='preview-major', name='数据库概论（示例）', school='信息科学技术学院'),
        CourseConfig(id='preview-elective', name='金融数据分析（示例）', school='软件与微电子学院', class_no=0),
        CourseConfig(id='preview-minor', name='概率统计（示例）', school='数学科学学院', identity='bfx'),
    ])
    config.extra_json['course_categories'] = {'preview-elective': 'elective'}
    ConfigService(paths, session_only=True).save(config)
    os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(paths.cache / 'webview')
    instance.APP_MUTEX = 'Local\\PKUCourseHelperOfflinePreview'
    app.DesktopBridge = PreviewBridge
    try:
        return app.run(paths)
    finally:
        # WebView2 can briefly retain cache handles; leave only disposable data
        # if Windows has not released the browser process yet.
        if profile.resolve().parent == root.resolve() and profile.name.startswith('.ui-preview-'):
            shutil.rmtree(profile, ignore_errors=True)
