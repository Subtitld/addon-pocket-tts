#!/usr/bin/env python3
"""Pin the Pocket TTS models and voices the add-on downloads: pocket_tts_addon/pins.json.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

The add-on downloads nothing it has not pinned here. For each model it offers,
this reads upstream's config at the release tag (pocket_tts/config/<model>.yaml),
keeps the files of kyutai/pocket-tts-without-voice-cloning that config names,
at the revisions it names, and asks Hugging Face for their size and sha256.
The model's built-in voices are the same repository's
languages/<model>/embeddings/<voice>.safetensors, at the revision the binary
names for them (src/defaults.rs, get_predefined_voice).

The config is kept as a template: its weight and tokenizer URLs become
{weights} and {tokenizer}, which the add-on replaces with the downloaded files,
so the binary reads only local files and never goes to the network. The line
pointing at kyutai/pocket-tts, the gated repository with voice cloning, is
dropped.

Small files Hugging Face stores outside LFS have no sha256 in its answer; they
are downloaded and hashed.

    git clone --branch v4.0.0 https://github.com/kyutai-labs/pocket-tts /tmp/pocket-tts
    python tools/pin_models.py /tmp/pocket-tts
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / 'pocket_tts_addon' / 'pins.json'

UPSTREAM_TAG = 'v4.0.0'
HF = 'https://huggingface.co'
OPEN_REPO = 'kyutai/pocket-tts-without-voice-cloning'
VOICE_REVISION = 'a3055dcb533cf2ec90458008a01e7cef550bae2a'

# What the add-on offers, from pocket_tts_addon/voices.py: every model x every voice.
sys.path.insert(0, str(REPO_ROOT))
from pocket_tts_addon.voices import MODELS, VOICES  # noqa: E402

_HF_PATH = re.compile(r'^hf://(?P<repo>[^/]+/[^/]+)/(?P<path>[^@]+)@(?P<rev>[0-9a-f]{40})$')


def _retrying(what: str, call):
    for attempt in range(1, 5):
        try:
            return call()
        except (OSError, urllib.error.URLError) as exc:
            if attempt == 4:
                raise SystemExit(f'FATAL: {what}: {exc}') from exc
            print(f'  retrying {what} ({exc})')
            time.sleep(5 * attempt)


def _paths_info(repo: str, revision: str, paths: list[str]) -> dict[str, dict]:
    body = urllib.parse.urlencode([('paths', p) for p in paths]).encode()
    url = f'{HF}/api/models/{repo}/paths-info/{revision}'

    def call():
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=120) as response:
            return json.load(response)
    return {entry['path']: entry for entry in _retrying(url, call)}


def _sha256_of_url(url: str) -> str:
    def call():
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=120) as response:
            while chunk := response.read(1 << 20):
                digest.update(chunk)
        return digest.hexdigest()
    return _retrying(url, call)


def _pin(repo: str, revision: str, path: str, info: dict) -> dict:
    entry = info.get(path)
    if entry is None:
        raise SystemExit(f'FATAL: {repo}@{revision} has no {path}')
    lfs = entry.get('lfs') or {}
    sha256 = lfs.get('oid') or _sha256_of_url(f'{HF}/{repo}/resolve/{revision}/{path}')
    return {'path': path, 'revision': revision, 'size': int(entry['size']), 'sha256': sha256}


def _config_template(text: str, name: str) -> tuple[str, dict, dict]:
    """The config with its URLs as placeholders, and the (path, revision) of each file."""
    files: dict[str, dict] = {}
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        key, _, value = stripped.partition(':')
        value = value.strip().strip('"\'')
        if key == 'weights_path' and line.startswith('weights_path'):
            continue  # the gated repository: replaced by the open one's weights below
        if key == 'weights_path_without_voice_cloning':
            match = _HF_PATH.match(value)
            if not match or match['repo'] != OPEN_REPO:
                raise SystemExit(f'FATAL: {name}: unexpected {key}: {value}')
            files['weights'] = match.groupdict()
            lines.append('weights_path: {weights}')
            continue
        if key == 'tokenizer_path':
            match = _HF_PATH.match(value)
            if not match or match['repo'] != OPEN_REPO:
                raise SystemExit(f'FATAL: {name}: unexpected {key}: {value}')
            files['tokenizer'] = match.groupdict()
            indent = line[:len(line) - len(line.lstrip())]
            lines.append(f'{indent}tokenizer_path: {{tokenizer}}')
            continue
        if 'hf://' in stripped or 'https://' in stripped:
            if not stripped.startswith('#'):
                raise SystemExit(f'FATAL: {name}: a URL the add-on would not pin: {stripped}')
        lines.append(line)
    if set(files) != {'weights', 'tokenizer'}:
        raise SystemExit(f'FATAL: {name}: found {sorted(files)}, expected weights and tokenizer')
    return '\n'.join(lines) + '\n', files['weights'], files['tokenizer']


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('upstream', type=Path, help=f'a checkout of kyutai-labs/pocket-tts at {UPSTREAM_TAG}')
    args = parser.parse_args(argv)

    described = subprocess.run(['git', '-C', str(args.upstream), 'describe', '--tags', '--exact-match'],
                               capture_output=True, text=True).stdout.strip()
    if described != UPSTREAM_TAG:
        raise SystemExit(f'FATAL: {args.upstream} is at {described or "no tag"}, expected {UPSTREAM_TAG}')
    defaults = (args.upstream / 'rust' / 'src' / 'defaults.rs').read_text(encoding='utf-8')
    if f'embeddings/{{name}}.safetensors@{VOICE_REVISION}' not in defaults:
        raise SystemExit('FATAL: the binary names another revision for its voices; update VOICE_REVISION')

    pins: dict = {'upstream': UPSTREAM_TAG, 'repo': OPEN_REPO, 'models': {}}
    for model in MODELS:
        text = (args.upstream / 'pocket_tts' / 'config' / f'{model.id}.yaml').read_text(encoding='utf-8')
        template, weights, tokenizer = _config_template(text, model.id)
        entry = {'config': template}
        for role, ref in (('weights', weights), ('tokenizer', tokenizer)):
            info = _paths_info(OPEN_REPO, ref['rev'], [ref['path']])
            entry[role] = _pin(OPEN_REPO, ref['rev'], ref['path'], info)
        voice_paths = [f'languages/{model.id}/embeddings/{voice.id}.safetensors' for voice in VOICES]
        info = _paths_info(OPEN_REPO, VOICE_REVISION, voice_paths)
        entry['voices'] = {voice.id: _pin(OPEN_REPO, VOICE_REVISION, path, info)
                           for voice, path in zip(VOICES, voice_paths)}
        pins['models'][model.id] = entry
        print(f'{model.id}: weights {entry["weights"]["size"]:,} bytes, {len(entry["voices"])} voices')

    OUT.write_text(json.dumps(pins, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'wrote {OUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
