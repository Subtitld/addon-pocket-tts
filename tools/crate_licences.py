#!/usr/bin/env python3
"""Write the notices of the code the pocket-tts binary links statically.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

The binary is Rust: it links about 400 crates, which its release does not list.
cargo-about (https://github.com/EmbarkStudios/cargo-about) reads upstream's
Cargo.lock at the release tag and gathers each crate's licence text, for the
targets the add-on ships (tools/cargo-about/about.toml). A crate under a
licence not accepted there fails the run.

Two crates compile C and C++ sources they vendor, whose notices cargo-about
does not gather or splits apart. Their files are appended as they are:
aws-lc-sys (AWS-LC, with BoringSSL and OpenSSL code) and sentencepiece-sys
(SentencePiece with Abseil, darts-clone, esaxx and protobuf-lite).

The result is committed, as THIRD_PARTY_LICENSES/pocket-tts/CRATES.txt; run
this again whenever tools/fetch_binary.py moves to another release.

    cargo install --locked cargo-about --features cli
    git clone --branch v4.0.0 https://github.com/kyutai-labs/pocket-tts /tmp/pocket-tts
    python tools/crate_licences.py /tmp/pocket-tts
"""

from __future__ import annotations

import argparse
import json
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ABOUT = REPO_ROOT / 'tools' / 'cargo-about'
OUT = REPO_ROOT / 'THIRD_PARTY_LICENSES' / 'pocket-tts' / 'CRATES.txt'

# Vendored sources, by crate: (path inside the crate, what it is).
VENDORED = {
    'aws-lc-sys': [
        ('aws-lc/LICENSE', 'AWS-LC, with code from BoringSSL and OpenSSL'),
    ],
    'sentencepiece-sys': [
        ('source/LICENSE', 'SentencePiece'),
        ('source/third_party/absl/LICENSE', 'Abseil (the parts SentencePiece vendors)'),
        ('source/third_party/darts_clone/LICENSE', 'darts-clone'),
        ('source/third_party/esaxx/LICENSE', 'esaxx'),
        ('source/third_party/protobuf-lite/LICENSE', 'Protocol Buffers (lite runtime)'),
    ],
}


def _crate_dirs(rust_dir: Path) -> dict[str, Path]:
    """Where cargo unpacked each crate, by name."""
    out = subprocess.run(['cargo', 'metadata', '--format-version', '1', '--locked'],
                         cwd=rust_dir, check=True, capture_output=True, text=True).stdout
    return {pkg['name']: Path(pkg['manifest_path']).parent for pkg in json.loads(out)['packages']}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('upstream', type=Path, help='a checkout of kyutai-labs/pocket-tts at the pinned release')
    args = parser.parse_args(argv)

    release = runpy.run_path(str(REPO_ROOT / 'tools' / 'fetch_binary.py'))['RELEASE']
    described = subprocess.run(['git', '-C', str(args.upstream), 'describe', '--tags', '--exact-match'],
                               capture_output=True, text=True).stdout.strip()
    if described != release:
        raise SystemExit(f'FATAL: {args.upstream} is at {described or "no tag"}, expected {release}')
    rust_dir = args.upstream / 'rust'

    with tempfile.TemporaryDirectory() as tmp:
        template = Path(tmp) / 'about.hbs'
        template.write_text((ABOUT / 'about.hbs').read_text(encoding='utf-8').replace('@TAG@', release),
                            encoding='utf-8')
        generated = Path(tmp) / 'crates.txt'
        subprocess.run(['cargo', 'about', 'generate', '--locked', '--fail',
                        '-c', str(ABOUT / 'about.toml'), str(template), '-o', str(generated)],
                       cwd=rust_dir, check=True)
        text = generated.read_text(encoding='utf-8').rstrip() + '\n'

    crates = _crate_dirs(rust_dir)
    parts = [text, '\n', '=' * 80, '\nC and C++ sources vendored by the crates above\n', '=' * 80, '\n']
    for crate, files in VENDORED.items():
        if crate not in crates:
            raise SystemExit(f'FATAL: {crate} is not in the lockfile any more; update VENDORED')
        for rel, what in files:
            path = crates[crate] / rel
            if not path.is_file():
                raise SystemExit(f'FATAL: {crate} has no {rel}')
            parts += ['\n', '-' * 80, f'\n{what} (in {crate}, {rel})\n\n',
                      path.read_text(encoding='utf-8').rstrip(), '\n']
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(''.join(parts), encoding='utf-8')
    print(f'wrote {OUT} ({OUT.stat().st_size:,} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
