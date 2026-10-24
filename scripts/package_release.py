"""Build matching Render static assets and a direct-upload Cloudflare Pages ZIP."""
import argparse
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package(output):
    repo=Path(__file__).resolve().parents[1]
    bundle=repo/'static.zip'
    frontend=repo/'cloudflare-pages/frontend'
    with ZipFile(bundle) as archive:
        files={entry.filename:archive.read(entry.filename) for entry in archive.infolist() if not entry.is_dir()}
    for source in frontend.rglob('*'):
        if source.is_file():
            files[source.relative_to(frontend).as_posix()]=source.read_bytes()
    html=files['index.html'].decode('utf-8')
    references=re.findall(r'(?:src|href)="/static/([^"?]+)',html)
    missing=[name for name in references if name not in files]
    if missing:
        raise RuntimeError('Missing frontend assets: '+', '.join(missing))
    for name in files:
        if name.startswith(('/', '\\')) or '..' in Path(name).parts:
            raise RuntimeError('Unsafe archive entry')
    updated=bundle.with_name('static-release.zip')
    with ZipFile(updated,'w',ZIP_DEFLATED) as archive:
        for name,data in files.items():
            archive.writestr(name,data)
    updated.replace(bundle)
    files['_worker.js']=(repo/'cloudflare-pages/_worker.js').read_bytes()
    output=output.resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for name,data in files.items():
            archive.writestr(name,data)
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        for source in frontend.rglob('*'):
            if source.is_file():
                assert archive.read(source.relative_to(frontend).as_posix())==source.read_bytes()
    print(f'Pages ZIP: {output}')
    print(f'Checked {len(references)} page references and {len(files)} packaged files.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    package(parser.parse_args().output)
