#!/usr/bin/env python3
"""Verify the distributable itself in an empty directory, then record evidence."""
from __future__ import annotations
import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from package import ARTIFACT_NAMES, OUT, ROOT, verify_archive

CHILD = '''
import json, sys, unittest
suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
count = suite.countTestCases()
result = unittest.TextTestRunner(verbosity=0).run(suite)
print(json.dumps({'tests': count, 'failures': len(result.failures), 'errors': len(result.errors),
                  'skipped': len(result.skipped), 'status': 'passed' if result.wasSuccessful() else 'failed'}))
sys.exit(0 if result.wasSuccessful() else 1)
'''


def main():
    archive = OUT / ARTIFACT_NAMES[0]
    files = verify_archive(archive)
    with tempfile.TemporaryDirectory(prefix='futarchist-release-') as directory:
        with zipfile.ZipFile(archive) as source:
            source.extractall(directory)
        project = Path(directory) / 'futarchist'
        required = ('futarchist/__main__.py', 'ownership/schema.sql', 'tests/fixtures/schema-v1.sql',
                    'ownership/static/assets/metadao.png', 'ownership/static/assets/futardio.png',
                    'ownership/static/assets/ownership.jpeg', 'ownership/static/assets/metadao-wordmark.jpeg',
                    'ownership/static/assets/futarchist-banner.jpeg', 'ownership/static/assets/futarchist-logo.jpeg')
        for name in required:
            if not (project / name).is_file():
                raise RuntimeError('Required source or original logo missing')
        process = subprocess.run([sys.executable, '-c', CHILD], cwd=project,
                                 capture_output=True, text=True, timeout=300)
    result = json.loads(process.stdout.strip().splitlines()[-1])
    evidence = {'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'kind': 'Fresh extraction of the distributable, checksum verification and full Python regression',
                'manifest_files': files, 'private_runtime_files': 'excluded', 'original_logo_files': 6,
                'backend': result, 'status': 'passed' if process.returncode == 0 else 'failed',
                'test_log': process.stderr}
    (ROOT / 'reports/package-check.json').write_text(json.dumps(evidence, indent=2))
    if process.returncode:
        print(process.stderr, file=sys.stderr)
        raise RuntimeError('Freshly extracted package failed regression checks')
    if result['tests'] != json.loads((ROOT / 'reports/test-results.json').read_text())['unique_test_cases']:
        raise RuntimeError('Packaged test count differs from checked source')
    path = ROOT / 'reports/test-results.json'
    report = json.loads(path.read_text())
    report['package_verification'] = {key: value for key, value in evidence.items() if key != 'test_log'}
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    page = ROOT / 'reports/test-report.html'
    document = page.read_text()
    start = document.find('<!-- package-verification -->')
    if start >= 0:
        end = document.index('<!-- /package-verification -->', start) + len('<!-- /package-verification -->')
        document = document[:start] + document[end:]
    section = ('<!-- package-verification --><h2>Distributable verification</h2>'
               '<p>The package was extracted into an empty directory. All file checksums, six original brand assets and '
               f"{result['tests']} Python tests passed. Private databases, configuration files "
               'and bot credentials are excluded.</p><!-- /package-verification -->')
    page.write_text(document.replace('</main>', section + '</main>'))
    print(json.dumps({key: value for key, value in evidence.items() if key != 'test_log'}, indent=2))


if __name__ == '__main__':
    main()
