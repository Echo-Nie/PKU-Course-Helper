import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def load_audit():
    spec = importlib.util.spec_from_file_location('audit_bundle', ROOT / 'tools' / 'audit_bundle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BundleAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'PKUCourseHelper'
        self.root.mkdir()
        self.write('PKUCourseHelper.exe', b'fake test executable')
        self.write('PKUCourseHelper.exe.config', (ROOT / 'packaging/PKUCourseHelper.exe.config').read_bytes())
        self.write('_internal/frontend/dist/index.html', b'<html></html>')
        self.write('_internal/resources/model/captcha.onnx', b'model')
        self.write('_internal/resources/model/manifest.json', json.dumps({'sha256': hashlib.sha256(b'model').hexdigest()}).encode())
        self.write('LICENSE.txt', b'Project license')
        self.write('licenses/MODEL-LICENSE.txt', b'Model license')
        self.write('licenses/THIRD-PARTY-NOTICES.json', b'[{"name":"samplelib","version":"1","license_files":["samplelib/LICENSE"]}]')
        self.write('licenses/samplelib/LICENSE', b'Test dependency license')
        self.write('_internal/webview/js/api.js', b'bridge')
        for name in ['WebView2Loader.dll', 'Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll', 'Python.Runtime.dll']:
            self.write('_internal/' + name, b'interop dll')

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def test_clean_bundle_has_all_file_hashes(self):
        audit = load_audit()
        result = audit.audit_bundle(self.root, inspect_archive=False)
        self.assertEqual(len(result['files']), 14)
        self.assertTrue(all(len(row['sha256']) == 64 for row in result['files']))

    def test_private_data_blocks_distribution(self):
        audit = load_audit()
        self.write('data/settings.json', b'{}')
        with self.assertRaisesRegex(audit.BundleAuditError, 'data/settings.json'):
            audit.audit_bundle(self.root, inspect_archive=False)

    def test_training_dependency_blocks_distribution(self):
        audit = load_audit()
        self.write('_internal/tensorflow/lib.dll', b'data')
        with self.assertRaisesRegex(audit.BundleAuditError, 'tensorflow'):
            audit.audit_bundle(self.root, inspect_archive=False)

    def test_corrupted_model_blocks_distribution(self):
        audit = load_audit()
        self.write('_internal/resources/model/captcha.onnx', b'bad model')
        with self.assertRaisesRegex(audit.BundleAuditError, 'model hash'):
            audit.audit_bundle(self.root, inspect_archive=False)

    def test_expanded_size_limit_is_enforced(self):
        audit = load_audit()
        with self.assertRaisesRegex(audit.BundleAuditError, 'expanded'):
            audit.audit_bundle(self.root, inspect_archive=False, expanded_limit=10)

    def test_archive_content_must_match_the_bundle(self):
        audit = load_audit()
        archive = Path(self.temporary.name) / 'release.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('PKUCourseHelper/data/credentials.dpapi', b'secret')
        with self.assertRaisesRegex(audit.BundleAuditError, 'ZIP content'):
            audit.audit_bundle(self.root, archive=archive, inspect_archive=False)

    def test_correct_zip_passes_and_compressed_limit_is_enforced(self):
        audit = load_audit()
        archive = Path(self.temporary.name) / 'release.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
            for path in self.root.rglob('*'):
                if path.is_file():
                    output.write(path, self.root.name + '/' + path.relative_to(self.root).as_posix())
        report = audit.audit_bundle(self.root, archive=archive, inspect_archive=False)
        self.assertEqual(report['zip_bytes'], archive.stat().st_size)
        with self.assertRaisesRegex(audit.BundleAuditError, 'ZIP size'):
            audit.audit_bundle(self.root, archive=archive, inspect_archive=False, zip_limit=10)

    def test_embedded_archive_cannot_be_skipped_in_release_audit(self):
        audit = load_audit()
        with self.assertRaisesRegex(audit.BundleAuditError, 'Python archive'):
            audit.audit_bundle(self.root)

    def test_model_manifest_requires_an_object(self):
        audit = load_audit()
        self.write('_internal/resources/model/manifest.json', b'[]')
        with self.assertRaisesRegex(audit.BundleAuditError, 'manifest'):
            audit.audit_bundle(self.root, inspect_archive=False)

    def test_missing_webview_bridge_blocks_distribution(self):
        audit = load_audit()
        (self.root / '_internal/webview/js/api.js').unlink()
        with self.assertRaisesRegex(audit.BundleAuditError, 'api.js'):
            audit.audit_bundle(self.root, inspect_archive=False)

    def installed_fixture(self):
        self.write('install-layout.ini', (ROOT / 'packaging/install-layout.ini').read_bytes())
        browser = b'offline browser fixture, not a real executable'
        self.write('runtime/webview2/msedgewebview2.exe', browser)
        receipt = {
            'version': 'fixture', 'cab_sha256': 'a' * 64,
            'signature_status': 'Valid', 'signer_subject': 'O=Microsoft Corporation',
            'files': [{'path': 'msedgewebview2.exe', 'bytes': len(browser),
                       'sha256': hashlib.sha256(browser).hexdigest()}],
        }
        self.write('runtime-manifest.json', json.dumps(receipt).encode())
        return receipt

    def test_installed_distribution_requires_private_runtime_receipt(self):
        audit = load_audit()
        self.installed_fixture()
        result = audit.audit_bundle(self.root, inspect_archive=False, distribution='installed')
        self.assertEqual(result['expanded_limit_bytes'], 1_500_000_000)
        with self.assertRaisesRegex(audit.BundleAuditError, 'Forbidden bundle content'):
            audit.audit_bundle(self.root, inspect_archive=False)

    def test_installed_runtime_rejects_modified_unlisted_and_duplicate_files(self):
        audit = load_audit()
        receipt = self.installed_fixture()
        receipt['files'].append(receipt['files'][0].copy())
        self.write('runtime-manifest.json', json.dumps(receipt).encode())
        with self.assertRaisesRegex(audit.BundleAuditError, 'duplicate runtime paths'):
            audit.audit_bundle(self.root, inspect_archive=False, distribution='installed')
        self.installed_fixture()
        self.write('runtime/webview2/msedgewebview2.exe', b'modified')
        with self.assertRaisesRegex(audit.BundleAuditError, 'hash mismatch'):
            audit.audit_bundle(self.root, inspect_archive=False, distribution='installed')
        self.write('runtime/webview2/unlisted.dll', b'unlisted')
        with self.assertRaisesRegex(audit.BundleAuditError, 'file set mismatch'):
            audit.audit_bundle(self.root, inspect_archive=False, distribution='installed')

    def test_private_portable_requires_its_own_marker_and_intact_runtime(self):
        audit = load_audit()
        self.installed_fixture()
        self.write('使用前请您务必阅读我.txt', b'Quick start')
        with self.assertRaisesRegex(audit.BundleAuditError, 'unexpected owner'):
            audit.audit_bundle(self.root, inspect_archive=False, distribution='portable-private')
        self.write('install-layout.ini', (ROOT / 'packaging/portable-layout.ini').read_bytes())
        result = audit.audit_bundle(self.root, inspect_archive=False, distribution='portable-private')
        self.assertEqual(result['distribution'], 'portable-private')
        self.write('runtime/webview2/msedgewebview2.exe', b'corrupted')
        with self.assertRaisesRegex(audit.BundleAuditError, 'hash mismatch'):
            audit.audit_bundle(self.root, inspect_archive=False, distribution='portable-private')

    def test_installed_runtime_does_not_accept_invalid_signature_or_owner(self):
        audit = load_audit()
        for key, value in [('signature_status', 'NotSigned'), ('signer_subject', 'unknown'),
                           ('cab_sha256', 'z' * 64)]:
            with self.subTest(key=key):
                receipt = self.installed_fixture()
                receipt[key] = value
                self.write('runtime-manifest.json', json.dumps(receipt).encode())
                with self.assertRaisesRegex(audit.BundleAuditError, 'provenance'):
                    audit.audit_bundle(self.root, inspect_archive=False, distribution='installed')
        self.installed_fixture()
        self.write('install-layout.ini', b'[Installation]\nProductId=another-app\n')
        with self.assertRaisesRegex(audit.BundleAuditError, 'Invalid installed payload'):
            audit.audit_bundle(self.root, inspect_archive=False, distribution='installed')

    def test_audit_rejects_links_without_reading_their_target_tree(self):
        audit = load_audit()
        outside = Path(self.temporary.name) / 'unrelated'
        outside.mkdir()
        (outside / 'keep.txt').write_bytes(b'outside the distribution')
        link = self.root / 'linked'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink privilege unavailable')
        original_scan = audit.os.scandir
        def guarded_scan(path):
            self.assertNotEqual(Path(path), link, 'Do not traverse redirected directories')
            return original_scan(path)
        with patch.object(audit.os, 'scandir', guarded_scan):
            with self.assertRaisesRegex(audit.BundleAuditError, 'symbolic link'):
                audit.audit_bundle(self.root, inspect_archive=False)


if __name__ == '__main__':
    unittest.main()
