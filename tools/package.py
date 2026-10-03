#!/usr/bin/env python3
"""Build portable FUTARCHIST deliverables without private runtime data."""
from __future__ import annotations
import base64
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / 'deliverables'
TOKEN = re.compile(rb'\b\d{5,}:[A-Za-z0-9_-]{25,}\b')
ARTIFACT_NAMES = ('FUTARCHIST_v2.zip', 'FUTARCHIST_Guide.html',
                  'FUTARCHIST_Test_Report.html', 'FUTARCHIST_Operations_v2.zip')


def contains_credential(data):
    # A JPEG's compressed bytes can coincidentally resemble a token. Scan text
    # credentials in source/configuration, retaining original binary logos.
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        return False
    return bool(TOKEN.search(data))


def allowed_files():
    paths = [ROOT / name for name in ('README.md', 'requirements.txt', '.env.example', '.gitignore', 'package.json', 'package-lock.json')
             if (ROOT / name).is_file()]
    for folder in ('futarchist', 'ownership', 'tests', 'docs', 'extensions', 'tools', 'reports'):
        for path in (ROOT / folder).rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            if any(part in ('__pycache__', 'screenshots', 'node_modules', '.venv', 'data') for part in path.parts):
                continue
            if path.name == '.env' or path.suffix in ('.pyc', '.sqlite3', '.sqlite', '.db', '.lock'):
                continue
            # Uploaded logos are intentional source assets, including PNGs.
            paths.append(path)
    return sorted(set(paths))


def write_archive(destination, files, prefix):
    manifest = {}
    entries = [(str(path.relative_to(ROOT)), path.read_bytes()) for path in files]
    if any(contains_credential(data) for _, data in entries):
        raise RuntimeError('Possible Telegram credential detected; refusing package')
    staging = destination.with_name(destination.name + '.building')
    try:
        with zipfile.ZipFile(staging, 'w', zipfile.ZIP_DEFLATED) as archive:
            for relative, data in entries:
                archive.writestr(prefix + '/' + relative, data)
                manifest[relative] = hashlib.sha256(data).hexdigest()
            archive.writestr(prefix + '/MANIFEST.json', json.dumps(manifest, indent=2))
        verify_archive(staging, prefix)
        staging.replace(destination)
    finally:
        staging.unlink(missing_ok=True)


def verify_archive(destination, prefix='futarchist'):
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip():
            raise RuntimeError('Archive integrity failed')
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError('Duplicate archive entry')
        for name in names:
            parts = Path(name).parts
            if not name.startswith(prefix + '/') or name.startswith('/') or '..' in parts:
                raise RuntimeError('Unsafe archive path')
            if any(part in ('.env', '.venv', 'data', 'node_modules', '__pycache__') for part in parts):
                raise RuntimeError('Runtime data included in archive')
        manifest = json.loads(archive.read(prefix + '/MANIFEST.json'))
        if {prefix + '/' + key for key in manifest} != set(names) - {prefix + '/MANIFEST.json'}:
            raise RuntimeError('Manifest does not cover the archive')
        for name, digest in manifest.items():
            data = archive.read(prefix + '/' + name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError('Archive checksum mismatch')
            if contains_credential(data):
                raise RuntimeError('Possible credential in archive')
    return len(manifest)


def standalone_guide():
    guide = (ROOT / 'ownership/static/guide.html').read_text()
    css = (ROOT / 'ownership/static/style.css').read_text()
    guide = guide.replace('<link rel="stylesheet" href="/style.css">', '<style>' + css + '</style>')

    def embed(match):
        path = ROOT / 'ownership/static' / match.group(1).lstrip('/')
        mime = mimetypes.guess_type(path.name)[0]
        if not path.is_file() or not mime or not mime.startswith('image/'):
            raise RuntimeError('Missing guide image')
        return 'src="data:' + mime + ';base64,' + base64.b64encode(path.read_bytes()).decode('ascii') + '"'

    guide = re.sub(r'src="(/assets/[^"<>]+)"', embed, guide)
    if '/assets/' in guide or '<link rel="stylesheet"' in guide:
        raise RuntimeError('Standalone guide contains local dependencies')
    return guide


def main():
    OUT.mkdir(exist_ok=True)
    report = json.loads((ROOT / 'reports/test-results.json').read_text())
    if report.get('backend_status') != 'passed' or report.get('dom_ui', {}).get('status') != 'passed':
        raise RuntimeError('Backend and DOM verification required before release packaging')
    files = allowed_files()
    write_archive(OUT / ARTIFACT_NAMES[0], files, 'futarchist')
    (OUT / ARTIFACT_NAMES[1]).write_text(standalone_guide())
    shutil.copyfile(ROOT / 'reports/test-report.html', OUT / ARTIFACT_NAMES[2])
    operations = [path for path in files if path.relative_to(ROOT).parts[0] in ('docs', 'extensions')]
    operations.append(ROOT / 'README.md')
    write_archive(OUT / ARTIFACT_NAMES[3], operations, 'FUTARCHIST_Operations_v2')
    summary = []
    for name in ARTIFACT_NAMES:
        path = OUT / name
        if path.suffix != '.zip' and contains_credential(path.read_bytes()):
            raise RuntimeError('Possible credential in deliverable')
        summary.append({'file': path.name, 'bytes': path.stat().st_size,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (OUT / 'FUTARCHIST_Checksums.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
