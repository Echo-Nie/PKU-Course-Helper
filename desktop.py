"""Portable entry point. No legacy or GUI imports before path initialization."""
import os
from pathlib import Path
import sys


def main():
    if '--worker' in sys.argv:
        from autoelective.desktop.runtime.worker import worker_main
        return worker_main()
    if '--self-test' in sys.argv:
        from autoelective.desktop.self_test import run_self_test
        index = sys.argv.index('--self-test')
        return run_self_test(Path(sys.argv[index + 1]))
    if '--preview' in sys.argv:
        from autoelective.desktop.preview import run_preview
        return run_preview()
    from autoelective.desktop.adapters.portable import PortablePaths
    root = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    instance = None
    try:
        if os.name == 'nt':
            from autoelective.desktop.platform.instance import acquire_instance
            instance = acquire_instance()
            if instance[0] is None:
                return 0
        paths = PortablePaths(root).initialize_environment()
        os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(paths.cache / 'webview')
        os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--disable-background-networking --disable-component-update --disable-breakpad'
        from autoelective.desktop.app import run
        return run(paths, instance=instance)
    except Exception as error:
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else '无法打开程序。请将完整软件包解压到可写文件夹后重试。'
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'PKUCourseHelper', 0x10)
        elif sys.stderr:
            print(message, file=sys.stderr)
        return 1
    finally:
        if instance and instance[0]:
            instance[1].CloseHandle(instance[0])


if __name__ == '__main__':
    raise SystemExit(main())
