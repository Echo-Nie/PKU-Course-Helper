"""Keep the download, frozen executable, CLR config and display name aligned."""
from pathlib import Path

import pytest

from test_release_assets import release


ROOT = Path(__file__).resolve().parents[2]
PRODUCT = 'PKUCourseHelper'


def test_product_identity_matches_the_complete_delivery_chain():
    assert release.ARCHIVE == PRODUCT + '-Windows11-x64-portable.zip'
    assert PRODUCT in release.ASSET_LABELS[release.ARCHIVE]
    assert {PRODUCT + '.exe', PRODUCT + '.exe.config'} <= release.AUDIT.PORTABLE_ROOT_FILES
    spec = (ROOT / 'packaging/portable.spec').read_text(encoding='utf-8-sig')
    assert spec.count("name='" + PRODUCT + "'") == 2
    for name in ('build_windows.ps1', 'build_private_portable.ps1'):
        script = (ROOT / 'packaging' / name).read_text(encoding='utf-8-sig')
        assert PRODUCT + '.exe' in script
        assert 'PKUAutoElective' not in script
    assert '<title>' + PRODUCT + '</title>' in (ROOT / 'frontend/index.html').read_text(encoding='utf-8')
    frontend = (ROOT / 'frontend/src/main.jsx').read_text(encoding='utf-8')
    assert '<h1>PKU Course Helper</h1>' in frontend
    # Respect the current icon-only brand; its accessible name and tooltip
    # retain the full product name without imposing a particular UI layout.
    assert 'aria-label="PKU Course Helper"' in frontend
    assert 'title="PKU Course Helper"' in frontend
    for name in ('desktop.py', 'desktop_dev.py', 'autoelective/desktop/app.py'):
        content = (ROOT / name).read_text(encoding='utf-8-sig')
        assert PRODUCT in content
        assert '选课工作台' not in content


def test_user_guide_has_one_required_delivery_filename():
    name = '使用前请您务必阅读我.txt'
    assert name in release.AUDIT.PORTABLE_ROOT_FILES
    assert '先读我.txt' not in release.AUDIT.PORTABLE_ROOT_FILES
    script = (ROOT / 'packaging/build_private_portable.ps1').read_text(encoding='utf-8-sig')
    assert "Copy-Item -LiteralPath $QuickStart -Destination (Join-Path $Payload '" + name + "')" in script
    guide = (ROOT / 'docs/QUICK_START.txt').read_text(encoding='utf-8')
    assert guide.startswith(PRODUCT + ' · 免安装版\n')
    assert 'https://github.com/Echo-Nie/PKU-Course-Helper' in guide


def test_exact_app_scoped_config_is_shipped_and_audited():
    config = ROOT / 'packaging' / (PRODUCT + '.exe.config')
    release.AUDIT.validate_app_runtime_config(config.read_bytes())
    build = (ROOT / 'packaging/build_windows.ps1').read_text(encoding='utf-8-sig')
    assert "Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'PKUCourseHelper.exe.config') -Destination $Bundle" in build


@pytest.mark.parametrize('content', [b'', b'<configuration/>', b'not XML',
    release.AUDIT.APP_RUNTIME_CONFIG.replace('enabled="true"', 'enabled="false"').encode(),
    release.AUDIT.APP_RUNTIME_CONFIG.replace('</runtime>', '<codeBase href="https://example.invalid/evil.dll"/></runtime>').encode()])
def test_missing_or_modified_netfx_config_blocks_distribution(content):
    with pytest.raises(release.AUDIT.BundleAuditError, match='startup configuration'):
        release.AUDIT.validate_app_runtime_config(content)
