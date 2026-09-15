"""Select the app-owned browser without installing shared components."""
import configparser
from pathlib import Path

PRODUCT_ID = '6AF68EC2-4877-4A72-B3EB-41776586D9DF'


def private_runtime(root):
    root = Path(root).resolve()
    marker = root / 'install-layout.ini'
    runtime = root / 'runtime' / 'webview2'
    if not marker.exists():
        if (root / 'runtime').exists():
            raise RuntimeError('安装信息缺失，请重新解压完整软件包；安装版请重新安装。')
        return None  # The separate portable build uses the existing system runtime.
    try:
        if marker.is_symlink() or marker.resolve().parent != root:
            raise ValueError('redirected marker')
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(marker.read_text(encoding='utf-8'))
        values = config['Installation']
        if (values['ProductId'] != PRODUCT_ID or values['SchemaVersion'] != '1'
                or values['Mode'] not in {'per-user-private-runtime', 'portable-private-runtime'}):
            raise ValueError('unknown installation')
        for path in (root / 'runtime', runtime, runtime / 'msedgewebview2.exe'):
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('redirected runtime')
        if not (runtime / 'msedgewebview2.exe').is_file():
            raise ValueError('missing runtime')
    except (OSError, ValueError, KeyError, configparser.Error) as error:
        raise RuntimeError('软件私有 WebView2 运行时缺失或目录异常，请重新解压完整软件包；安装版请重新安装。') from error
    return runtime
