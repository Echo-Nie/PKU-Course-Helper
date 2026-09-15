"""Collect Python and frontend dependency notices into the portable bundle."""

import argparse
from importlib import metadata
import json
from pathlib import Path
import re
import shutil
import sys


def safe_name(value):
    return re.sub(r'[^A-Za-z0-9._-]', '_', value)


def is_notice(path):
    return any(Path(path).name.lower().startswith(prefix) for prefix in ('license', 'licence', 'copying', 'notice'))


def collect(output, frontend):
    output.mkdir(parents=True, exist_ok=True)
    notices = []
    for distribution in sorted(metadata.distributions(), key=lambda item: item.metadata['Name'].lower()):
        name, version = distribution.metadata['Name'], distribution.version
        directory = output / safe_name(name + '-' + version)
        license_files = []
        for number, source_name in enumerate(distribution.files or []):
            if not is_notice(source_name):
                continue
            source = Path(distribution.locate_file(source_name))
            if source.is_file():
                directory.mkdir(exist_ok=True)
                target = directory / (str(number) + '-' + safe_name(source.name))
                shutil.copyfile(source, target)
                license_files.append(target.relative_to(output).as_posix())
        if not license_files:
            license_text = distribution.metadata.get('License') or distribution.metadata.get('License-Expression')
            if not license_text or license_text.upper() == 'UNKNOWN':
                raise RuntimeError('Missing license metadata for dependency: ' + name)
            directory.mkdir(exist_ok=True)
            target = directory / 'METADATA-LICENSE.txt'
            target.write_text(license_text + '\n', encoding='utf-8')
            license_files.append(target.relative_to(output).as_posix())
        notices.append({'name': name, 'version': version, 'ecosystem': 'python', 'license_files': license_files})

    python_license = next((Path(sys.base_prefix) / name for name in ['LICENSE.txt', 'LICENSE'] if (Path(sys.base_prefix) / name).is_file()), None)
    if python_license is None:
        # uv-managed Python puts the license beside lib/python3.x on some hosts.
        python_license = next(Path(sys.base_prefix).glob('lib/python*/LICENSE.txt'), None)
    if python_license is None:
        raise RuntimeError('Python distribution license was not found')
    shutil.copyfile(python_license, output / 'PYTHON-LICENSE.txt')
    notices.append({'name': 'Python', 'version': sys.version.split()[0], 'ecosystem': 'python', 'license_files': ['PYTHON-LICENSE.txt']})

    lock = json.loads((frontend / 'package-lock.json').read_text(encoding='utf-8'))
    for package_path, package in sorted(lock['packages'].items()):
        if not package_path or package.get('dev') or package.get('optional'):
            continue
        source = frontend / package_path
        package_metadata = json.loads((source / 'package.json').read_text(encoding='utf-8'))
        name, version = package_metadata['name'], package_metadata['version']
        directory = output / ('npm-' + safe_name(name + '-' + version))
        directory.mkdir(exist_ok=True)
        license_files = []
        for item in sorted(source.iterdir()):
            if item.is_file() and is_notice(item):
                target = directory / safe_name(item.name)
                shutil.copyfile(item, target)
                license_files.append(target.relative_to(output).as_posix())
        if not license_files:
            raise RuntimeError('No license file for frontend dependency: ' + name)
        notices.append({'name': name, 'version': version, 'ecosystem': 'npm', 'license_files': license_files})
    (output / 'THIRD-PARTY-NOTICES.json').write_text(json.dumps(notices, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('Collected notices for', len(notices), 'dependencies')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frontend', type=Path, required=True)
    arguments = parser.parse_args()
    collect(arguments.output.resolve(), arguments.frontend.resolve())
