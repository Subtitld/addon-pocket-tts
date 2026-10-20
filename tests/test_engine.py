"""engine.py with a stand-in for the pocket-tts binary.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

The stand-in is a Python script that records how it was called and then
does what $FAKE_MODE says: write a WAV, fail, hang, or die of SIGILL. POSIX
only, since it relies on a shebang; tests/test_installed.py runs the real
binary on every platform.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
import time
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pocket_tts_addon import download, engine  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='the stand-in binary is a shebang script')

FAKE = r'''#!{python}
import json, os, signal, sys, time, wave
args = sys.argv[1:]
record = {{'args': args, 'env': {{k: v for k, v in os.environ.items()
                                 if k.startswith(('POCKET_TTS', 'HF_', 'RAYON', 'LD_LIBRARY'))}}}}
with open(os.environ['FAKE_RECORD'], 'w') as f:
    json.dump(record, f)
mode = os.environ.get('FAKE_MODE', 'ok')
if mode == 'fail':
    print('ERROR: cannot read the config', file=sys.stderr)
    sys.exit(3)
if mode == 'hang':
    time.sleep(60)
if mode == 'sigill':
    os.kill(os.getpid(), signal.SIGILL)
out = args[args.index('--output-path') + 1]
with wave.open(out, 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
    w.writeframes(b'\0\0' * 24000)
'''


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    binary = tmp_path / 'pocket-tts'
    binary.write_text(FAKE.format(python=sys.executable), encoding='utf-8')
    binary.chmod(0o644)  # as the host's ZipFile.extractall leaves it
    monkeypatch.setenv('POCKET_TTS_BINARY', str(binary))
    monkeypatch.setenv('SUBTITLD_MODELS_DIR', str(tmp_path / 'models'))
    monkeypatch.setenv('FAKE_RECORD', str(tmp_path / 'record.json'))
    monkeypatch.setenv('HF_TOKEN', 'secret')
    monkeypatch.setenv('RAYON_NUM_THREADS', '64')
    return tmp_path


def _record(tmp_path: Path) -> dict:
    return json.loads((tmp_path / 'record.json').read_text(encoding='utf-8'))


def test_a_line_is_spoken_from_local_files_only(fake):
    out = fake / 'out' / 'line.wav'
    speech = engine.synthesize('Hello there.', 'english', 'vera', out, seed=7)
    assert speech.duration_sec == pytest.approx(1.0)
    assert speech.sample_rate == 24000
    assert out.is_file()
    assert not [p for p in out.parent.iterdir() if p.name.startswith('.pocket-tts-')]
    assert os.stat(engine.binary_path()).st_mode & stat.S_IXUSR, 'the binary was made executable'

    record = _record(fake)
    args = record['args']
    assert args[:2] == ['generate', '--quiet']
    assert args[args.index('--text') + 1] == 'Hello there.'
    voice = Path(args[args.index('--voice') + 1])
    assert voice == download.local_path(engine.pins()['models']['english']['voices']['vera'])
    config = Path(args[args.index('--config') + 1]).read_text(encoding='utf-8')
    weights = download.local_path(engine.pins()['models']['english']['weights'])
    assert f'weights_path: {json.dumps(str(weights))}' in config
    assert 'hf://' not in config
    assert '--quantize' not in args

    env = record['env']
    assert env['POCKET_TTS_SEED'] == '7'
    assert env['HF_HUB_OFFLINE'] == '1'
    assert 'HF_TOKEN' not in env
    assert 'RAYON_NUM_THREADS' not in env


def test_quantize_is_passed_on(fake):
    engine.synthesize('Hi.', 'french', 'estelle', fake / 'q.wav', quantize=True)
    assert '--quantize' in _record(fake)['args']


def test_a_failure_carries_the_binary_s_message(fake, monkeypatch):
    monkeypatch.setenv('FAKE_MODE', 'fail')
    out = fake / 'fail.wav'
    with pytest.raises(engine.EngineError, match='exit 3.*cannot read the config'):
        engine.synthesize('Hi.', 'english', 'alba', out)
    assert not out.exists()


def test_a_missing_instruction_says_so(fake, monkeypatch):
    monkeypatch.setenv('FAKE_MODE', 'sigill')
    with pytest.raises(engine.UnsupportedCPU, match='AVX2'):
        engine.synthesize('Hi.', 'english', 'alba', fake / 'ill.wav')


def test_a_cancel_kills_the_line(fake, monkeypatch):
    monkeypatch.setenv('FAKE_MODE', 'hang')
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(download.Cancelled):
        engine.synthesize('Hi.', 'english', 'alba', fake / 'hang.wav', cancel=cancel)
    assert time.monotonic() - started < 10


def test_a_missing_binary_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv('POCKET_TTS_BINARY', str(tmp_path / 'nothing'))
    with pytest.raises(engine.EngineError, match='missing'):
        engine.synthesize('Hi.', 'english', 'alba', tmp_path / 'x.wav')


def test_the_config_survives_awkward_paths(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBTITLD_MODELS_DIR', str(tmp_path / 'a folder with "quotes" and: colons'))
    path = engine.config_path('english')
    text = path.read_text(encoding='utf-8')
    line = next(l for l in text.splitlines() if l.startswith('weights_path:'))
    assert json.loads(line.split(':', 1)[1].strip()).startswith(str(tmp_path))
