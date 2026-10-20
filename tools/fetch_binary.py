#!/usr/bin/env python3
"""Fetch and verify the pocket-tts binary that the build bundles.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

The binary is Kyutai's own standalone build of Pocket TTS (MIT), from the
GitHub release of kyutai-labs/pocket-tts. Each archive is checked against the
sha256 pinned here, which is the one the release's SHA256SUMS lists. Nothing
here runs when the add-on runs: the frozen add-on only ever starts the binary
this script placed in the output folder.

    python tools/fetch_binary.py                         # this machine
    python tools/fetch_binary.py --platform windows-x86_64
    python tools/fetch_binary.py --out build/assets
"""

from __future__ import annotations

import argparse
import hashlib
import io
import platform
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

RELEASE = 'v4.0.0'
# The release names its archives after the Rust package version.
PACKAGE_VERSION = '3.3.0'
BASE = f'https://github.com/kyutai-labs/pocket-tts/releases/download/{RELEASE}/'

# platform key -> (Rust target, archive sha256 from the release's SHA256SUMS)
PLATFORMS = {
    'linux-x86_64': ('x86_64-unknown-linux-gnu',
                     '1336a77e60ce11650a5a3dc354770155a345bfa797f7a05d10bc5b1bcfe0d7e3'),
    'linux-aarch64': ('aarch64-unknown-linux-gnu',
                      '644a9478d7cbd7d432f5a4898007aa7d178a897a65aef7ebc64557e0b1a1739a'),
    'macos-arm64': ('aarch64-apple-darwin',
                    'e209feca849d53df18eba89f5bd4c253c1be62a6c54794db5654635c95e02990'),
    'macos-x86_64': ('x86_64-apple-darwin',
                     '3a908c524d1ca976eb5f699c523fbdd47a5fa029ccc3bd9f6197b8f8d91f01c1'),
    'windows-x86_64': ('x86_64-pc-windows-msvc',
                       'b3b2faa74703c505e22a7f428c984f69577548c85440c4c9eee0d336797f3cef'),
}


def archive_name(platform_key: str) -> str:
    target, _sha = PLATFORMS[platform_key]
    suffix = '.zip' if 'windows' in target else '.tar.gz'
    return f'pocket-tts-{PACKAGE_VERSION}-{target}{suffix}'


def binary_name(platform_key: str) -> str:
    return 'pocket-tts.exe' if platform_key.startswith('windows') else 'pocket-tts'


def detect_platform() -> str:
    machine = platform.machine().lower()
    arm = machine in ('arm64', 'aarch64')
    if sys.platform == 'darwin':
        return 'macos-arm64' if arm else 'macos-x86_64'
    if sys.platform == 'win32':
        return 'windows-x86_64'
    if sys.platform.startswith('linux'):
        return 'linux-aarch64' if arm else 'linux-x86_64'
    raise SystemExit(f'FATAL: no pinned binary for {sys.platform} {machine}; '
                     f'pass --platform with one of: {", ".join(PLATFORMS)}')


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download(url: str, cache: Path, expected_sha: str) -> bytes:
    """The archive at `url`, from the cache when a verified copy is there."""
    cached = cache / url.rsplit('/', 1)[1]
    if cached.is_file():
        data = cached.read_bytes()
        if _sha256(data) == expected_sha:
            print(f'cached: {cached.name}')
            return data
    print(f'downloading: {url}')
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    actual = _sha256(data)
    if actual != expected_sha:
        raise SystemExit(f'FATAL: {cached.name} sha256 is {actual}, expected {expected_sha}')
    cache.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data


def _members(data: bytes, name: str) -> dict[str, bytes]:
    """The archive's files, by base name."""
    files: dict[str, bytes] = {}
    if name.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if not info.is_dir():
                    files[info.filename.rsplit('/', 1)[-1]] = archive.read(info)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            for member in archive.getmembers():
                if member.isfile():
                    files[member.name.rsplit('/', 1)[-1]] = archive.extractfile(member).read()
    return files


def fetch(platform_key: str, out: Path, cache: Path) -> Path:
    _target, sha = PLATFORMS[platform_key]
    name = archive_name(platform_key)
    files = _members(_download(BASE + name, cache, sha), name)
    binary = binary_name(platform_key)
    if binary not in files or 'LICENSE' not in files:
        raise SystemExit(f'FATAL: {name} holds {sorted(files)}, expected {binary} and LICENSE')
    out.mkdir(parents=True, exist_ok=True)
    dest = out / binary
    dest.write_bytes(files[binary])
    dest.chmod(0o755)
    (out / 'pocket-tts-LICENSE').write_bytes(files['LICENSE'])
    print(f'{dest}: {dest.stat().st_size:,} bytes sha256={_sha256(files[binary])}')
    return dest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--platform', choices=sorted(PLATFORMS), default=None)
    parser.add_argument('--out', type=Path, default=Path('build') / 'assets')
    parser.add_argument('--cache', type=Path, default=Path('build') / 'downloads')
    args = parser.parse_args(argv)
    fetch(args.platform or detect_platform(), args.out, args.cache)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
