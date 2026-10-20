"""The add-on as Subtitld runs it: a process spoken to over stdio, speaking for real.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

By default the process is the source tree (`python -m pocket_tts_addon`) with
the binary from tools/fetch_binary.py. With POCKET_TTS_TEST_BINARY set it is
that executable instead, which is how the release workflow runs these tests:
on the frozen add-on unpacked from the release zip the way Subtitld installs
it, with nothing but what is inside its own bundle.

The models download from Hugging Face into $SUBTITLD_MODELS_DIR (a temporary
folder when it is not set): the English model, 226 MB, and the small English
one, 112 MB.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pocket_tts_addon import engine  # noqa: E402

BINARY = os.environ.get('POCKET_TTS_TEST_BINARY')
HAVE_BINARY = bool(BINARY) or engine.binary_path().is_file()

pytestmark = pytest.mark.skipif(not HAVE_BINARY, reason='no pocket-tts binary; run tools/fetch_binary.py')

_MODELS = Path(os.environ.get('SUBTITLD_MODELS_DIR') or tempfile.mkdtemp(prefix='pocket-tts-models-'))


def _start(cwd: Path, **extra_env: str) -> subprocess.Popen:
    env = dict(os.environ)
    env['SUBTITLD_MODELS_DIR'] = str(_MODELS)
    env.update(extra_env)
    if BINARY:
        # The bundle's own binary and code, nothing from this checkout.
        env.pop('POCKET_TTS_BINARY', None)
        env.pop('PYTHONPATH', None)
        command = [BINARY]
    else:
        env['PYTHONPATH'] = str(REPO_ROOT)
        command = [sys.executable, '-m', 'pocket_tts_addon']
    return subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _say(proc, req_id: str, out: Path, **params) -> tuple[dict, list[dict]]:
    params = {'output_path': str(out), **params}
    proc.stdin.write((json.dumps({'id': req_id, 'type': 'tts.synthesize', 'params': params}) + '\n').encode())
    proc.stdin.flush()
    progress = []
    while True:
        line = proc.stdout.readline()
        assert line, proc.stderr.read().decode('utf-8', 'replace')
        frame = json.loads(line)
        if frame.get('id') != req_id:
            continue
        if frame['type'] == 'progress':
            progress.append(frame)
            continue
        return frame, progress


def _check_wav(path: Path, at_least_sec: float) -> float:
    with wave.open(str(path), 'rb') as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        seconds = wav.getnframes() / wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    assert seconds >= at_least_sec
    assert any(frames[i] for i in range(0, len(frames), 97)), 'the audio is silent'
    return seconds


@pytest.mark.parametrize('size, line', [
    ('standard', 'The door was already open when I got here, so I walked in.'),
    ('small', 'We have twenty minutes before the train leaves.'),
])
def test_speaks_a_line(tmp_path, size, line):
    proc = _start(tmp_path, POCKET_TTS_MODEL=size)
    try:
        hello = json.loads(proc.stdout.readline())
        assert hello['type'] == 'hello'
        out = tmp_path / 'out' / 'line.wav'
        frame, progress = _say(proc, 'r1', out, text=line, voice='vera', language='en-US', seed=3)
        assert frame['type'] == 'result', frame
        assert frame['data']['sample_rate'] == 24000 and frame['data']['voice'] == 'vera'
        assert _check_wav(out, 1.5) == pytest.approx(frame['data']['duration_sec'], abs=0.01)
        assert progress[-1]['value'] == 1.0

        # A second voice on the same model downloads only the voice.
        frame, progress = _say(proc, 'r2', tmp_path / 'out' / 'second.wav',
                               text='Thank you.', voice='george', language='en')
        assert frame['type'] == 'result', frame
        assert not any('model' in p['message'] for p in progress)
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
        proc.stdout.close()
        proc.stderr.close()
