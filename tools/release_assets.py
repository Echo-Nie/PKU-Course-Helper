"""Stage, verify and publish an allowlisted Windows release; no school access."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import quote
import xml.etree.ElementTree as ET


# GitHub strips Chinese characters from asset filenames. Keep the download
# filename ASCII and provide the friendly Chinese text as the asset label.
ARCHIVE = 'PKUCourseHelper-Windows11-x64-portable.zip'
ASSET_LABELS = {ARCHIVE: 'PKUCourseHelper · Windows 11 x64 免安装版', 'SHA256SUMS.txt': 'SHA-256 文件校验'}
REPORTS = ('bundle-audit.json', 'pytest-windows.xml', 'frozen-self-test.json')
ASSETS = frozenset({ARCHIVE, 'SHA256SUMS.txt'})
EVIDENCE = frozenset((*REPORTS, 'release-manifest.json'))
_spec = importlib.util.spec_from_file_location('release_bundle_audit', Path(__file__).with_name('audit_bundle.py'))
AUDIT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(AUDIT)


def version(value):
    match = re.fullmatch(r'v?((0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?)', value)
    if not match or any(int(part) > 65535 for part in match.group(1).split('-')[0].split('.')):
        raise ValueError('Use a version such as v1.2.3 or v1.2.3-rc.1; numeric parts must be <= 65535.')
    return match.group(1)


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def validate_evidence(directory):
    public, evidence = directory / 'public', directory / 'evidence'
    report = read_json(evidence / 'frozen-self-test.json')
    if report.get('passed') is not True or report.get('frozen') is not True or report.get('platform') != 'Windows':
        raise ValueError('Not a passing frozen Windows self-test.')
    audit = read_json(evidence / 'bundle-audit.json')
    if (audit.get('distribution') != 'portable-private' or not audit.get('files')
            or audit.get('platform') != 'windows-x64' or not audit.get('embedded_python_entries')):
        raise ValueError('Missing audited, self-contained portable Windows x64 payload.')
    if audit.get('zip_sha256') != sha256(public / ARCHIVE):
        raise ValueError('Audit evidence belongs to a different ZIP.')
    AUDIT.audit_portable_zip(public / ARCHIVE, audit['files'])
    suites = list(ET.parse(evidence / 'pytest-windows.xml').iter('testsuite'))
    if not suites or sum(int(s.get('tests', '0')) for s in suites) <= 0 or any(
            int(s.get('failures', '0')) or int(s.get('errors', '0')) for s in suites):
        raise ValueError('Python test evidence is empty or contains failures.')


def prepare(build_root, destination, app_version, commit, tag, inputs):
    app_version = version(app_version)
    if tag and version(tag) != app_version:
        raise ValueError('Release tag and portable version disagree.')
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('A full source commit SHA is required.')
    archives = list(build_root.rglob(ARCHIVE))
    if len(archives) != 1:
        raise ValueError('Expected exactly one portable ZIP build.')
    if not 0 < archives[0].stat().st_size <= AUDIT.PRIVATE_PORTABLE_ZIP_LIMIT:
        raise ValueError('Portable ZIP is empty or exceeds 600 MB.')
    destination.mkdir(parents=True, exist_ok=False)  # Never mix old and new builds.
    public, evidence = destination / 'public', destination / 'evidence'
    public.mkdir()
    evidence.mkdir()
    shutil.copyfile(archives[0], public / ARCHIVE)
    for name in REPORTS:
        shutil.copyfile(archives[0].parent / name, evidence / name)
    validate_evidence(destination)
    manifest = {'schema_version': 1, 'version': app_version, 'tag': tag, 'commit': commit,
                'platform': 'windows-x64', 'distribution': 'portable-private', 'build_inputs': read_json(inputs),
                'report_hashes': {name: sha256(evidence / name) for name in REPORTS},
                'not_certified': ['live_school_requests', 'native_visual_journeys', '240_hour_endurance'],
                'executable_signed': False}
    (evidence / 'release-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (public / 'SHA256SUMS.txt').write_text(f'{sha256(public / ARCHIVE)}  {ARCHIVE}\n', encoding='utf-8')


def verify(directory, commit, event=None):
    if ({p.name for p in directory.iterdir()} != {'public', 'evidence'}
            or any(not p.is_dir() or p.is_symlink() for p in directory.iterdir())):
        raise ValueError('Release artifact must separate public delivery and build evidence.')
    public, evidence = directory / 'public', directory / 'evidence'
    for root, expected in ((public, ASSETS), (evidence, EVIDENCE)):
        if {p.name for p in root.iterdir()} != expected or any(not p.is_file() or p.is_symlink() for p in root.iterdir()):
            raise ValueError('Unexpected, missing, redirected or private files in release assets.')
    expected_sums = f'{sha256(public / ARCHIVE)}  {ARCHIVE}\n'
    if (public / 'SHA256SUMS.txt').read_text(encoding='utf-8') != expected_sums:
        raise ValueError('ZIP checksum mismatch, duplicate or unexpected checksum entry.')
    if not 0 < (public / ARCHIVE).stat().st_size <= AUDIT.PRIVATE_PORTABLE_ZIP_LIMIT:
        raise ValueError('Portable ZIP size gate failed.')
    manifest = read_json(evidence / 'release-manifest.json')
    if manifest.get('commit') != commit or not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('Artifacts were built from a different source commit.')
    version(manifest['version'])
    if manifest.get('distribution') != 'portable-private':
        raise ValueError('This release must be a self-contained portable ZIP.')
    if manifest.get('report_hashes') != {name: sha256(evidence / name) for name in REPORTS}:
        raise ValueError('Build evidence checksum mismatch.')
    if event is not None:
        release = event.get('release', {})
        if event.get('action') != 'published' or release.get('draft') is not False:
            raise ValueError('Only a published release may receive these assets.')
        if manifest.get('tag') != release.get('tag_name') or version(release['tag_name']) != manifest['version']:
            raise ValueError('Artifacts do not belong to the triggering release tag.')
    validate_evidence(directory)
    return manifest


def gh_api(endpoint, *, file=None):
    command = ['gh', 'api', endpoint]
    if file is not None:
        command += ['--method', 'POST', '-H', 'Content-Type: application/octet-stream', '--input', str(file)]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', timeout=900)
    except subprocess.CalledProcessError as error:
        # gh does not receive account data; expose bounded API feedback rather
        # than hiding the useful HTTP/permission/immutable-release diagnostic.
        raise RuntimeError('GitHub API request failed: ' + error.stderr.strip()[:2000]) from None
    return json.loads(result.stdout)


def publish(directory, repository, event, api=gh_api):
    directory = directory / 'public'  # Never publish the evidence directory.
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid GitHub repository.')
    release_id = event['release']['id']
    if type(release_id) is not int or release_id <= 0:
        raise ValueError('Invalid release ID.')
    endpoint = f'repos/{repository}/releases/{release_id}'
    current = api(endpoint)
    if current.get('draft') is not False or current.get('tag_name') != event['release']['tag_name']:
        raise ValueError('Release was changed or returned to draft during the build.')
    if current.get('immutable'):
        raise ValueError('This release is immutable; published assets cannot be added. See docs/RELEASING.md.')
    assets = {a['name']: a for a in current['assets']}
    # Preflight ALL collisions before uploading anything. Never clobber a public asset.
    for name in sorted(ASSETS):
        if name in assets and assets[name].get('digest') != 'sha256:' + sha256(directory / name):
            raise ValueError(f'An existing release asset differs or has no verifiable digest: {name}. No overwrite performed.')
    for name in sorted(ASSETS):
        if name in assets:
            continue  # Re-running a partially completed upload is safe.
        upload = (f'https://uploads.github.com/{endpoint}/assets?name={quote(name, safe="")}'
                  f'&label={quote(ASSET_LABELS[name], safe="")}')
        result = api(upload, file=directory / name)
        if result.get('name') != name or result.get('digest') != 'sha256:' + sha256(directory / name):
            raise ValueError(f'Uploaded asset did not return the expected name and SHA-256: {name}')
    final_assets = {a['name']: a for a in api(endpoint)['assets']}
    if any(final_assets.get(name, {}).get('digest') != 'sha256:' + sha256(directory / name) for name in ASSETS):
        raise ValueError('Final GitHub release asset verification failed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    meta = sub.add_parser('version')
    meta.add_argument('value')
    stage = sub.add_parser('prepare')
    for name in ('build-root', 'destination', 'inputs'):
        stage.add_argument('--' + name, type=Path, required=True)
    stage.add_argument('--version', required=True)
    stage.add_argument('--tag', default='')
    stage.add_argument('--commit', required=True)
    for name in ('verify', 'publish'):
        check = sub.add_parser(name)
        check.add_argument('--directory', type=Path, required=True)
        check.add_argument('--commit', required=True)
        check.add_argument('--event', type=Path, required=name == 'publish')
    args = parser.parse_args()
    if args.command == 'version':
        print(version(args.value))
    elif args.command == 'prepare':
        prepare(args.build_root, args.destination, args.version, args.commit, args.tag, args.inputs)
    else:
        event = read_json(args.event) if args.event else None
        verify(args.directory, args.commit, event)
        if args.command == 'publish':
            if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_EVENT_NAME') != 'release':
                raise ValueError('Publishing is restricted to a GitHub Actions release event.')
            if not os.environ.get('GH_TOKEN'):
                raise ValueError('Missing GH_TOKEN for the release upload job.')
            publish(args.directory, os.environ['GITHUB_REPOSITORY'], event)
        print('Release assets verified.' if args.command == 'verify' else 'Release assets uploaded and verified.')


if __name__ == '__main__':
    main()
