"""Fail-closed, offline audit of portable and privately installed payloads."""

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import zipfile


ZIP_LIMIT = 150_000_000
EXPANDED_LIMIT = 350_000_000
INSTALLED_EXPANDED_LIMIT = 1_500_000_000
PRIVATE_PORTABLE_ZIP_LIMIT = 600_000_000
FORBIDDEN_MODULES = (
    'tensorflow', 'tf2onnx', 'keras', 'cv2', 'torch', 'PySide', 'PyQt',
    'cefpython', 'pytest', 'notebook', 'autoelective.captcha.model',
    'autoelective.desktop.ui',
)
FORBIDDEN_PARTS = {
    '.git', '.venv', '.venv-desktop', 'node_modules', '__pycache__',
    'tensorflow', 'tf2onnx', 'keras', 'cv2', 'torch', 'pyside6', 'pyside2',
    'pyqt5', 'pyqt6', 'qt6', 'qt5', 'cefpython3', 'tests', 'test',
}
PRIVATE_NAMES = {
    'config.ini', 'settings.json', 'credentials.dpapi', 'user_agents.user.txt',
    '.env', 'cookies.txt', 'cookies.json',
}
APP_RUNTIME_CONFIG = '''<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <runtime>
    <loadFromRemoteSources enabled="true" />
  </runtime>
</configuration>'''
PORTABLE_ROOT_FILES = {'PKUCourseHelper.exe', 'PKUCourseHelper.exe.config', '使用前请您务必阅读我.txt', 'LICENSE.txt',
                       'install-layout.ini', 'runtime-manifest.json'}
PORTABLE_ROOT_DIRS = {'_internal', 'runtime', 'licenses'}


def clean_portable_path(relative, is_directory=False):
    """Allow only the delivery layout; keep third-party runtime/license files intact."""
    parts = relative.split('/')
    if (not relative or '\\' in relative or ':' in relative
            or any(part in {'', '.', '..'} for part in parts)):
        return False
    if len(parts) == 1:
        return parts[0] in (PORTABLE_ROOT_DIRS if is_directory else PORTABLE_ROOT_FILES)
    if parts[0] not in PORTABLE_ROOT_DIRS:
        return False
    lowered = [part.lower() for part in parts]
    if any(part in FORBIDDEN_PARTS | {'reports', 'artifacts', '.github', '.pytest_cache'} for part in lowered):
        return False
    if '/'.join(lowered[:2]) in {'_internal/maintenance', '_internal/tools', '_internal/packaging', '_internal/autoelective'}:
        return False
    if lowered[:3] == ['_internal', 'frontend', 'src']:
        return False
    upstream_license_viewer = relative == 'runtime/webview2/show_third_party_software_licenses.bat'
    if lowered[-1] in PRIVATE_NAMES or (Path(relative).suffix.lower() in {'.log', '.dpapi', '.reg', '.pdb', '.ps1', '.bat', '.cmd', '.map'} and not upstream_license_viewer):
        return False
    if lowered[-1] in {'pytest-windows.xml', 'bundle-audit.json', 'payload-audit.json',
                        'frozen-self-test.json', 'release-manifest.json', 'sha256sums.txt'}:
        return False
    return True


def audit_portable_zip(archive, expected_files):
    """Recheck the actual delivery ZIP on Windows or the Linux publication job."""
    expected = {row['path']: row for row in expected_files}
    if not expected or len(expected) != len(expected_files):
        raise BundleAuditError('Empty or duplicate portable file manifest')
    if Path(archive).stat().st_size > PRIVATE_PORTABLE_ZIP_LIMIT:
        raise BundleAuditError('Portable ZIP exceeds size limit')
    seen = set()
    total = 0
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            if info.filename == 'PKUCourseHelper/' and info.is_dir():
                continue
            if not info.filename.startswith('PKUCourseHelper/'):
                raise BundleAuditError('Unexpected ZIP root: ' + info.filename)
            name = info.filename.removeprefix('PKUCourseHelper/').rstrip('/')
            if not clean_portable_path(name, info.is_dir()) or (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise BundleAuditError('Unclean or redirected ZIP entry: ' + info.filename)
            if info.is_dir():
                continue
            if name in seen or name not in expected:
                raise BundleAuditError('Duplicate or unlisted ZIP file: ' + name)
            seen.add(name)
            total += info.file_size
            if total > INSTALLED_EXPANDED_LIMIT or info.file_size != expected[name]['bytes']:
                raise BundleAuditError('ZIP expanded size mismatch or limit exceeded')
            with source.open(info) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != expected[name]['sha256']:
                raise BundleAuditError('ZIP file hash mismatch: ' + name)
            if name == 'PKUCourseHelper.exe.config':
                validate_app_runtime_config(source.read(info))
    if seen != set(expected) or not PORTABLE_ROOT_FILES.issubset(seen):
        raise BundleAuditError('Portable ZIP is missing required files')
    for prefix in ('_internal/', 'runtime/webview2/', 'licenses/'):
        if not any(name.startswith(prefix) for name in seen):
            raise BundleAuditError('Missing portable runtime/license directory: ' + prefix)
    return {'files': len(seen), 'expanded_bytes': total, 'zip_sha256': sha256(Path(archive))}


class BundleAuditError(ValueError):
    pass


def validate_app_runtime_config(content):
    try:
        valid = content.decode('utf-8-sig').replace('\r\n', '\n').strip() == APP_RUNTIME_CONFIG
    except UnicodeError:
        valid = False
    if not valid:
        raise BundleAuditError('Missing or unexpected app-local .NET startup configuration')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _bundle_paths(root):
    """Never descend into symlinks or Windows junctions while auditing."""
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda entry: entry.name)
        for entry in children:
            path = Path(entry.path)
            attributes = entry.stat(follow_symlinks=False)
            redirected = entry.is_symlink() or bool(getattr(attributes, 'st_file_attributes', 0) & 0x400)
            yield path, redirected
            if not redirected and entry.is_dir(follow_symlinks=False):
                pending.append(path)


def _inspect_python_archive(executable):
    try:
        from PyInstaller.archive.readers import CArchiveReader
        archive = CArchiveReader(str(executable))
        entries = list(archive.toc)
        pyz_names = [name for name in entries if name.lower().endswith('.pyz')]
        if not pyz_names:
            raise BundleAuditError('No embedded Python archive found')
        for name in pyz_names:
            entries.extend(archive.open_embedded_archive(name).toc)
        banned = [name for name in entries if any(name.lower().startswith(prefix.lower()) for prefix in FORBIDDEN_MODULES)]
        if banned:
            raise BundleAuditError('Forbidden embedded modules: ' + ', '.join(sorted(banned)))
        return len(entries)
    except BundleAuditError:
        raise
    except Exception as error:
        raise BundleAuditError('Cannot inspect executable Python archive: ' + str(error)) from error


def audit_bundle(root, archive=None, inspect_archive=True, expanded_limit=None, zip_limit=None,
                 distribution='portable'):
    if distribution not in {'portable', 'installed', 'portable-private'}:
        raise BundleAuditError('Unknown distribution mode')
    private = distribution in {'installed', 'portable-private'}
    if expanded_limit is None:
        expanded_limit = INSTALLED_EXPANDED_LIMIT if private else EXPANDED_LIMIT
    if zip_limit is None:
        zip_limit = PRIVATE_PORTABLE_ZIP_LIMIT if distribution == 'portable-private' else ZIP_LIMIT
    root = Path(root).resolve()
    if not root.is_dir():
        raise BundleAuditError('Bundle directory does not exist')
    files = []
    violations = []
    for path, redirected in _bundle_paths(root):
        relative = path.relative_to(root).as_posix()
        parts = relative.lower().split('/')
        if redirected:
            violations.append(relative + ' (symbolic link)')
            continue
        if distribution == 'portable-private' and not clean_portable_path(relative, path.is_dir()):
            violations.append(relative)
        # A shipping directory has no user profile, even if it is empty.
        if parts[0] in {'data', 'cache', 'log', 'logs', 'tmp'}:
            violations.append(relative)
        if any(part in FORBIDDEN_PARTS for part in parts):
            violations.append(relative)
        if path.is_dir():
            continue
        if path.name.lower() in PRIVATE_NAMES or path.suffix.lower() in {'.log', '.dpapi', '.reg', '.pdb'}:
            violations.append(relative)
        if path.name.lower() in {'msedge.exe', 'chrome.exe', 'msedgewebview2.exe', 'webview2setup.exe', 'microsoftedgewebview2setup.exe'}:
            if not (private and parts[:2] == ['runtime', 'webview2']
                    and path.name.lower() == 'msedgewebview2.exe'):
                violations.append(relative)
        if '.model-' in path.name or path.suffix.lower() in {'.meta', '.tfrecords'}:
            violations.append(relative)
        files.append({'path': relative, 'bytes': path.stat().st_size, 'sha256': sha256(path)})
    files.sort(key=lambda row: row['path'])
    if violations:
        raise BundleAuditError('Forbidden bundle content: ' + ', '.join(sorted(set(violations))))

    required = [
        'PKUCourseHelper.exe', 'PKUCourseHelper.exe.config', '_internal/frontend/dist/index.html',
        '_internal/resources/model/captcha.onnx', '_internal/resources/model/manifest.json',
        '_internal/webview/js/api.js',
        'LICENSE.txt', 'licenses/MODEL-LICENSE.txt', 'licenses/THIRD-PARTY-NOTICES.json',
    ]
    if distribution == 'portable-private':
        required.append('使用前请您务必阅读我.txt')
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise BundleAuditError('Missing required files: ' + ', '.join(missing))
    validate_app_runtime_config((root / 'PKUCourseHelper.exe.config').read_bytes())
    filenames = {Path(row['path']).name.lower() for row in files}
    interop = ['WebView2Loader.dll', 'Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll', 'Python.Runtime.dll']
    missing_interop = [name for name in interop if name.lower() not in filenames]
    if missing_interop:
        raise BundleAuditError('Missing runtime interop DLLs: ' + ', '.join(missing_interop))
    try:
        notices = json.loads((root / 'licenses' / 'THIRD-PARTY-NOTICES.json').read_text(encoding='utf-8'))
        if not isinstance(notices, list) or not notices:
            raise ValueError('empty third-party notices')
        for notice in notices:
            if not isinstance(notice, dict) or not notice.get('license_files'):
                raise ValueError('empty dependency license files')
            for license_name in notice['license_files']:
                license_path = (root / 'licenses' / license_name).resolve()
                if not license_path.is_relative_to(root / 'licenses') or not license_path.is_file():
                    raise ValueError('missing license: ' + license_name)
        manifest = json.loads((root / '_internal/resources/model/manifest.json').read_text(encoding='utf-8'))
        if not isinstance(manifest, dict):
            raise ValueError('model manifest must be an object')
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise BundleAuditError('Invalid model/license manifest: ' + str(error)) from error
    if sha256(root / '_internal/resources/model/captcha.onnx') != manifest.get('sha256'):
        raise BundleAuditError('Captcha model hash does not match manifest')
    if private:
        try:
            owner = configparser.ConfigParser(interpolation=None)
            owner.read_string((root / 'install-layout.ini').read_text(encoding='utf-8'))
            if (owner['Installation']['ProductId'] != '6AF68EC2-4877-4A72-B3EB-41776586D9DF'
                    or owner['Installation']['SchemaVersion'] != '1'
                    or owner['Installation']['Mode'] != ('portable-private-runtime' if distribution == 'portable-private' else 'per-user-private-runtime')):
                raise ValueError('unexpected owner')
            runtime = json.loads((root / 'runtime-manifest.json').read_text(encoding='utf-8-sig'))
            if (runtime['signature_status'] != 'Valid'
                    or 'Microsoft Corporation' not in runtime['signer_subject']
                    or not re.fullmatch(r'[0-9a-fA-F]{64}', runtime['cab_sha256'])):
                raise ValueError('missing verified runtime provenance')
            expected = {row['path']: row for row in runtime['files']}
            actual = {row['path'].removeprefix('runtime/webview2/'): row for row in files
                      if row['path'].startswith('runtime/webview2/')}
            if 'msedgewebview2.exe' not in actual or set(actual) != set(expected):
                raise ValueError('private runtime file set mismatch')
            if len(expected) != len(runtime['files']):
                raise ValueError('duplicate runtime paths')
            for name, row in actual.items():
                if (row['sha256'] != expected[name]['sha256']
                        or row['bytes'] != expected[name]['bytes']):
                    raise ValueError('private runtime hash mismatch: ' + name)
        except (OSError, KeyError, TypeError, ValueError, configparser.Error) as error:
            raise BundleAuditError('Invalid installed payload: ' + str(error)) from error
    expanded_size = sum(row['bytes'] for row in files)
    if expanded_size > expanded_limit:
        raise BundleAuditError(f'Bundle expanded size {expanded_size} exceeds {expanded_limit} bytes')
    report = {
        'schema_version': 1, 'platform': 'windows-x64', 'distribution': distribution,
        'expanded_bytes': expanded_size, 'expanded_limit_bytes': expanded_limit,
        'files': files,
    }
    if inspect_archive:
        report['embedded_python_entries'] = _inspect_python_archive(root / 'PKUCourseHelper.exe')
    if archive is not None:
        archive = Path(archive)
        if distribution == 'portable-private':
            audit_portable_zip(archive, files)
        compressed_size = archive.stat().st_size
        if compressed_size > zip_limit:
            raise BundleAuditError(f'ZIP size {compressed_size} exceeds {zip_limit} bytes')
        expected = {root.name + '/' + row['path']: row for row in files}
        try:
            with zipfile.ZipFile(archive) as source:
                entries = [info for info in source.infolist() if not info.is_dir()]
                if len(entries) != len(expected) or {info.filename for info in entries} != set(expected):
                    raise BundleAuditError('ZIP content does not match the audited bundle')
                for info in entries:
                    digest = hashlib.sha256()
                    with source.open(info) as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(block)
                    if info.file_size != expected[info.filename]['bytes'] or digest.hexdigest() != expected[info.filename]['sha256']:
                        raise BundleAuditError('ZIP content hash mismatch: ' + info.filename)
        except zipfile.BadZipFile as error:
            raise BundleAuditError('Invalid ZIP archive') from error
        report.update({'zip_bytes': compressed_size, 'zip_limit_bytes': zip_limit, 'zip_sha256': sha256(archive)})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--distribution', choices=['portable', 'installed', 'portable-private'], default='portable')
    parser.add_argument('--report', type=Path, required=True, help='Write outside the bundle to avoid self-referential hashes')
    args = parser.parse_args()
    if args.report.resolve().is_relative_to(args.bundle.resolve()):
        parser.error('--report must be outside the bundle')
    try:
        report = audit_bundle(args.bundle, archive=args.archive, distribution=args.distribution)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    except (OSError, BundleAuditError) as error:
        print('Bundle audit failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps({key: value for key, value in report.items() if key != 'files'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
