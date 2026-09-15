import copy
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import hashlib
from urllib.parse import quote
import zipfile

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_assets', ROOT / 'tools/release_assets.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
COMMIT = 'a' * 40
EVENT = {'action': 'published', 'release': {'id': 123, 'tag_name': 'v1.2.3-rc.1', 'draft': False}}


@pytest.mark.parametrize('value,expected', [('v1.2.3', '1.2.3'), ('1.2.3-rc.1', '1.2.3-rc.1'), ('0.0.0', '0.0.0')])
def test_versions(value, expected):
    assert release.version(value) == expected


@pytest.mark.parametrize('value', ['', 'main', '1.2', '01.2.3', '65536.0.0', 'v1.2.3\n', '1.2.3;whoami',
                                 '1.2.3-rc..1', '../1.2.3', '1.2.3+unsafe', '"1.2.3"'])
def test_reject_unsafe_versions(value):
    with pytest.raises(ValueError):
        release.version(value)


@pytest.fixture
def assets(tmp_path):
    build = tmp_path / 'build' / 'unique-build'
    build.mkdir(parents=True)
    payload = {name: b'offline fixture' for name in release.AUDIT.PORTABLE_ROOT_FILES}
    payload['PKUCourseHelper.exe.config'] = (ROOT / 'packaging/PKUCourseHelper.exe.config').read_bytes()
    payload.update({'_internal/frontend/dist/index.html': b'<html/>',
                    'runtime/webview2/msedgewebview2.exe': b'offline browser fixture',
                    'licenses/MODEL-LICENSE.txt': b'license fixture'})
    with zipfile.ZipFile(build / release.ARCHIVE, 'w') as archive:
        for name, data in payload.items():
            archive.writestr('PKUCourseHelper/' + name, data)
    rows = [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()} for name, data in payload.items()]
    (build / 'bundle-audit.json').write_text(json.dumps(
        {'distribution': 'portable-private', 'files': rows, 'platform': 'windows-x64',
         'embedded_python_entries': 100, 'zip_sha256': release.sha256(build / release.ARCHIVE)}), encoding='utf-8')
    (build / 'pytest-windows.xml').write_text('<testsuites><testsuite tests="10" failures="0" errors="0"/></testsuites>')
    report = json.dumps({'passed': True, 'frozen': True, 'platform': 'Windows'})
    (build / 'frozen-self-test.json').write_text(report)
    destination = tmp_path / 'assets'
    release.prepare(build.parent, destination, '1.2.3-rc.1', COMMIT, EVENT['release']['tag_name'],
                    ROOT / 'packaging/release-inputs.json')
    return destination


def test_staged_assets_are_allowlisted_and_verified(assets):
    assert {p.name for p in assets.iterdir()} == {'public', 'evidence'}
    assert {p.name for p in (assets / 'public').iterdir()} == {release.ARCHIVE, 'SHA256SUMS.txt'}
    assert release.verify(assets, COMMIT, EVENT)['version'] == '1.2.3-rc.1'


@pytest.mark.parametrize('damage', ['missing', 'extra', 'tampered', 'duplicate', 'traversal', 'commit', 'tag', 'draft', 'action'])
def test_verify_fails_closed(assets, damage):
    event = copy.deepcopy(EVENT)
    commit = COMMIT
    checksums = assets / 'public/SHA256SUMS.txt'
    if damage == 'missing':
        (assets / 'evidence/frozen-self-test.json').unlink()
    elif damage == 'extra':
        (assets / 'public/settings.json').write_text('private config must never be uploaded')
    elif damage == 'tampered':
        (assets / 'public' / release.ARCHIVE).write_bytes(b'tampered')
    elif damage == 'duplicate':
        checksums.write_text(checksums.read_text(encoding='utf-8') + checksums.read_text(encoding='utf-8').splitlines()[0] + '\n', encoding='utf-8')
    elif damage == 'traversal':
        checksums.write_text('a' * 64 + '  ../secret.txt\n')
    elif damage == 'commit':
        commit = 'b' * 40
    elif damage == 'tag':
        event['release']['tag_name'] = 'v9.9.9'
    elif damage == 'draft':
        event['release']['draft'] = True
    elif damage == 'action':
        event['action'] = 'edited'
    with pytest.raises(ValueError):
        release.verify(assets, commit, event)


@pytest.mark.parametrize('failure', ['pytest', 'frozen', 'other_zip', 'audit'])
def test_evidence_must_pass(assets, failure):
    if failure == 'pytest':
        (assets / 'evidence/pytest-windows.xml').write_text('<testsuites><testsuite tests="1" errors="1"/></testsuites>')
    else:
        names = {'frozen': 'frozen-self-test.json', 'other_zip': 'bundle-audit.json', 'audit': 'bundle-audit.json'}
        path = assets / 'evidence' / names[failure]
        data = release.read_json(path)
        if failure == 'other_zip':
            data['zip_sha256'] = '0' * 64
        elif failure == 'audit':
            data['distribution'] = 'portable'
        else:
            data['passed'] = False
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        release.validate_evidence(assets)


class FakeGitHub:
    def __init__(self):
        self.release = {**EVENT['release'], 'immutable': False, 'assets': []}
        self.uploads = []

    def __call__(self, endpoint, *, file=None):
        if file is None:
            return copy.deepcopy(self.release)
        assert endpoint == (f'https://uploads.github.com/repos/example/project/releases/123/assets?name={quote(file.name, safe="")}'
                            f'&label={quote(release.ASSET_LABELS[file.name], safe="")}')
        # Model the real API's filename normalization, not an idealized echo.
        item = {'name': re.sub(r'[^A-Za-z0-9._-]', '', file.name), 'digest': 'sha256:' + release.sha256(file)}
        self.uploads.append(file.name)
        self.release['assets'].append(item)
        return item


def test_publish_and_retry_skip_verified_assets(assets):
    api = FakeGitHub()
    release.publish(assets, 'example/project', EVENT, api)
    assert set(api.uploads) == release.ASSETS
    release.publish(assets, 'example/project', EVENT, api)
    assert len(api.uploads) == len(release.ASSETS)


def test_release_filenames_survive_github_normalization():
    assert all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name) for name in release.ASSETS)
    assert set(release.ASSET_LABELS) == release.ASSETS
    assert '免安装' in release.ASSET_LABELS[release.ARCHIVE]
    script = (ROOT / 'packaging/build_private_portable.ps1').read_text(encoding='utf-8-sig')
    assert f"$Archive = Join-Path $Output '{release.ARCHIVE}'" in script


def test_publish_resume_after_partial_network_failure(assets):
    api = FakeGitHub()
    def interrupted(endpoint, *, file=None):
        if file and len(api.uploads) == 1:
            raise TimeoutError('fake network outage')
        return api(endpoint, file=file)
    with pytest.raises(TimeoutError):
        release.publish(assets, 'example/project', EVENT, interrupted)
    release.publish(assets, 'example/project', EVENT, api)
    assert len(api.uploads) == len(release.ASSETS)


@pytest.mark.parametrize('damage', ['collision', 'no_digest', 'immutable', 'retagged', 'draft'])
def test_publish_never_overwrites_or_uploads_to_changed_release(assets, damage):
    api = FakeGitHub()
    if damage in ('collision', 'no_digest'):
        api.release['assets'] = [{'name': release.ARCHIVE, 'digest': 'sha256:' + '0' * 64 if damage == 'collision' else None}]
    elif damage == 'immutable':
        api.release['immutable'] = True
    elif damage == 'draft':
        api.release['draft'] = True
    else:
        api.release['tag_name'] = 'v9.9.9'
    with pytest.raises(ValueError):
        release.publish(assets, 'example/project', EVENT, api)
    assert not api.uploads


def test_workflow_privilege_and_trigger_contract():
    # BaseLoader deliberately avoids YAML 1.1 interpreting the GitHub key "on" as True.
    workflow = yaml.load((ROOT / '.github/workflows/windows-release.yml').read_text(encoding='utf-8'), Loader=yaml.BaseLoader)
    assert workflow['on']['release']['types'] == ['published']
    assert set(workflow['on']) == {'release', 'workflow_dispatch'}
    assert workflow['permissions'] == {'contents': 'read'}
    build, publish = workflow['jobs']['build'], workflow['jobs']['publish']
    assert build['runs-on'] == 'windows-2022'
    assert publish['needs'] == 'build' and "github.event_name == 'release'" in publish['if']
    assert publish['permissions'] == {'contents': 'write'}
    for job in (build, publish):
        for step in job['steps']:
            if 'uses' in step:
                assert re.fullmatch(r'[\w-]+/[\w-]+@[a-f0-9]{40}', step['uses'])
    download = next(s for s in publish['steps'] if 'download-artifact@' in s.get('uses', ''))
    assert download['with']['artifact-ids'] == '${{ needs.build.outputs.artifact_id }}'
    assert download['with']['merge-multiple'] == 'true'
    assert download['with']['digest-mismatch'] == 'error'


def test_gh_api_errors_retain_useful_feedback(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ['gh', 'api'], stderr='HTTP 403: Resource not accessible by integration')
    monkeypatch.setattr(release.subprocess, 'run', fail)
    with pytest.raises(RuntimeError, match='HTTP 403'):
        release.gh_api('repos/example/project/releases/123')


def test_release_builds_only_portable_and_never_installs_tools():
    workflow = (ROOT / '.github/workflows/windows-release.yml').read_text(encoding='utf-8')
    setup = (ROOT / 'packaging/setup_release_tools.ps1').read_text(encoding='utf-8')
    assert 'build_private_portable.ps1' in workflow
    for unwanted in ('build_installer.ps1', 'check_installer_windows.ps1', 'INNO_COMPILER', 'installer-qa'):
        assert unwanted not in workflow
    assert 'Start-Process' not in setup and 'innosetup' not in setup.lower()


def test_pinned_release_inputs():
    inputs = release.read_json(ROOT / 'packaging/release-inputs.json')
    assert set(inputs) == {'schema_version', 'webview2'}
    for name in ('webview2',):
        assert re.fullmatch('[a-f0-9]{64}', inputs[name]['sha256'])
        assert inputs[name]['url'].startswith('https://')
        assert inputs[name]['version'] in inputs[name]['url']


def test_tool_installer_refuses_local_execution():
    import os
    import shutil
    shell = shutil.which('pwsh') or shutil.which('powershell')
    if not shell:
        pytest.skip('PowerShell not available')
    env = dict(os.environ, GITHUB_ACTIONS='false', PSModuleAnalysisCachePath='NUL')
    result = subprocess.run([shell, '-NoLogo', '-NoProfile', '-NonInteractive', '-File',
                             str(ROOT / 'packaging/setup_release_tools.ps1')],
                            env=env, capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode != 0
    assert 'restricted to disposable' in result.stderr


@pytest.mark.parametrize('unwanted', ['README.md', '使用说明.md', 'tests/case.py', 'data/settings.json',
    'PKUCourseHelper-windows-x64-setup.exe', '_internal/artifacts/report.json', '_internal/settings.json',
    '_internal/frontend/src/main.jsx', '_internal/uninstall_cleanup.ps1', '_internal/maintenance/cleanup.ps1',
    '_internal/logs/session.log', '_internal/.env', '_internal/frontend/dist/index.html.map',
    'runtime/webview2/debug.pdb', 'bundle-audit.json', '../outside.txt', '_internal/../secret.txt'])
def test_zip_rejects_development_private_and_installer_content(assets, unwanted):
    archive = assets / 'public' / release.ARCHIVE
    audit = release.read_json(assets / 'evidence/bundle-audit.json')
    data = b'must not ship'
    with zipfile.ZipFile(archive, 'a') as output:
        output.writestr('PKUCourseHelper/' + unwanted, data)
    # Even a manifest listing and hashing this extra file cannot authorize it.
    audit['files'].append({'path': unwanted, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    with pytest.raises(ValueError, match='Unclean'):
        release.AUDIT.audit_portable_zip(archive, audit['files'])


def test_zip_rejects_even_empty_data_directory(assets):
    archive = assets / 'public' / release.ARCHIVE
    with zipfile.ZipFile(archive, 'a') as output:
        output.writestr('PKUCourseHelper/data/', b'')
    with pytest.raises(ValueError, match='Unclean'):
        release.AUDIT.audit_portable_zip(archive, release.read_json(assets / 'evidence/bundle-audit.json')['files'])


def test_keep_verified_upstream_license_viewer_but_not_developer_scripts():
    assert release.AUDIT.clean_portable_path('runtime/webview2/show_third_party_software_licenses.bat')
    assert not release.AUDIT.clean_portable_path('runtime/webview2/install.bat')
    assert not release.AUDIT.clean_portable_path('_internal/show_third_party_software_licenses.bat')


def test_zip_rejects_missing_guide_and_duplicate_files(assets):
    archive = assets / 'public' / release.ARCHIVE
    audit = release.read_json(assets / 'evidence/bundle-audit.json')
    with pytest.warns(UserWarning, match='Duplicate'):
        with zipfile.ZipFile(archive, 'a') as output:
            output.writestr('PKUCourseHelper/PKUCourseHelper.exe', b'fake')
    with pytest.raises(ValueError, match='Duplicate'):
        release.AUDIT.audit_portable_zip(archive, audit['files'])
