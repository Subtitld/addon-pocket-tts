"""Run Kyutai's pocket-tts binary on local files only.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

The binary
----------
Kyutai's standalone `pocket-tts` (MIT, a Rust port of Pocket TTS) is in the
archive, verified against its release's SHA256SUMS by tools/fetch_binary.py.
One `pocket-tts generate` runs per line: loading a model takes a fraction of a
second, the process holds nothing between lines, and a cancel kills it.

Local files only
----------------
Upstream's configs name Hugging Face URLs, the gated repository with voice
cloning first. The add-on writes its own config for each model instead
(pins.json holds them as templates), naming the weights and the tokenizer it
downloaded, and passes each voice as its downloaded .safetensors file. The
binary is never handed a URL, and $HF_TOKEN is kept from it.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

from pocket_tts_addon import download

log = logging.getLogger('pocket_tts_addon.engine')

_PINS_FILE = Path(__file__).resolve().parent / 'pins.json'
_pins: dict | None = None

# How the process ends when the CPU lacks an instruction the binary uses.
# The x86-64 builds need AVX2 and FMA (x86-64-v3): Intel since 2013 (Haswell),
# AMD since 2015 (Excavator), but not every Celeron, Pentium or Atom.
_SIGILL = -4                      # POSIX: killed by SIGILL
_STATUS_ILLEGAL_INSTRUCTION = 0xC000001D  # Windows


class EngineError(Exception):
    """The binary failed; the message says why."""


class UnsupportedCPU(EngineError):
    """The binary needs instructions this CPU lacks."""


def pins() -> dict:
    global _pins
    if _pins is None:
        _pins = json.loads(_PINS_FILE.read_text(encoding='utf-8'))
    return _pins


def files_for(model: str, voice: str) -> list[dict]:
    """The pins a line needs: the model's weights and tokenizer, and the voice."""
    entry = pins()['models'][model]
    return [entry['weights'], entry['tokenizer'], entry['voices'][voice]]


# ---------------------------------------------------------------------------
# The binary
# ---------------------------------------------------------------------------
def binary_name() -> str:
    return 'pocket-tts.exe' if sys.platform == 'win32' else 'pocket-tts'


def binary_path() -> Path:
    """$POCKET_TTS_BINARY, else the archive's assets/, else build/assets/ in a source tree."""
    override = (os.environ.get('POCKET_TTS_BINARY') or '').strip()
    if override:
        return Path(os.path.expanduser(override))
    bundled = getattr(sys, '_MEIPASS', None)  # PyInstaller onedir: the `_internal` folder
    if bundled:
        return Path(bundled) / 'assets' / binary_name()
    return Path(__file__).resolve().parent.parent / 'build' / 'assets' / binary_name()


def ensure_executable(binary: Path) -> None:
    """Make the binary runnable.

    Subtitld installs an add-on with ZipFile.extractall, which drops permission
    bits, and then marks only the manifest's `executable` as runnable. The
    add-on's install folder is the user's own, so the bit can be set here.
    """
    if sys.platform == 'win32' or os.access(binary, os.X_OK):
        return
    try:
        binary.chmod(binary.stat().st_mode | 0o111)
    except OSError as exc:
        raise EngineError(f'Cannot make {binary} executable: {exc}. Reinstall the add-on.') from exc


def _no_window_startupinfo():
    """Keep a console window from flashing on Windows GUI hosts."""
    if sys.platform != 'win32':
        return None
    si = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    si.wShowWindow = subprocess.SW_HIDE  # type: ignore[attr-defined]
    return si


def _child_env(seed: int) -> dict:
    env = dict(os.environ)
    # The frozen Linux bootloader prepends the bundle's `_internal/` to
    # LD_LIBRARY_PATH; the binary must load the system's libstdc++, not
    # whatever the bundle carries. PyInstaller keeps the host's value in
    # LD_LIBRARY_PATH_ORIG.
    if getattr(sys, 'frozen', False) and sys.platform.startswith('linux'):
        original = env.pop('LD_LIBRARY_PATH_ORIG', None)
        if original is not None:
            env['LD_LIBRARY_PATH'] = original
        else:
            env.pop('LD_LIBRARY_PATH', None)
    for name in ('HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN', 'HF_TOKEN_PATH'):
        env.pop(name, None)
    env['HF_HUB_OFFLINE'] = '1'
    env['POCKET_TTS_SEED'] = str(seed)
    # Without it the binary takes four threads, which upstream measured fastest
    # for a model this small.
    env.pop('RAYON_NUM_THREADS', None)
    return env


# ---------------------------------------------------------------------------
# Configs
# ---------------------------------------------------------------------------
def _yaml_string(path: Path) -> str:
    # A JSON string is a YAML double-quoted scalar: safe for any path,
    # Windows backslashes and spaces included.
    return json.dumps(str(path))


def config_path(model: str) -> Path:
    """Write the model's config, naming the downloaded files, and return its path."""
    entry = pins()['models'][model]
    text = entry['config'].format(
        weights=_yaml_string(download.local_path(entry['weights'])),
        tokenizer=_yaml_string(download.local_path(entry['tokenizer'])),
    )
    path = download.cache_root() / 'configs' / f'{model}.yaml'
    try:
        if path.read_text(encoding='utf-8') == text:
            return path
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + '.tmp')
    scratch.write_text(text, encoding='utf-8')
    os.replace(scratch, path)
    return path


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------
@dataclass
class Speech:
    path: Path
    duration_sec: float
    sample_rate: int
    seconds: float  # wall time


def _illegal_instruction(returncode: int) -> bool:
    return returncode == _SIGILL or (sys.platform == 'win32'
                                     and returncode & 0xFFFFFFFF == _STATUS_ILLEGAL_INSTRUCTION)


def synthesize(text: str, model: str, voice: str, output: Path, *, seed: int = 42,
               quantize: bool = False,
               cancel: threading.Event | None = None) -> Speech:
    """Speak `text` into `output` (16-bit mono WAV, 24 kHz). The files must be downloaded."""
    binary = binary_path()
    if not binary.is_file():
        raise EngineError(f'The pocket-tts program is missing from the add-on ({binary}). '
                          f'Reinstall the add-on.')
    ensure_executable(binary)
    cancel = cancel or threading.Event()
    voice_file = download.local_path(pins()['models'][model]['voices'][voice])
    output.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the output and renamed, so the host never sees half a file.
    fd, scratch_name = tempfile.mkstemp(prefix='.pocket-tts-', suffix='.wav', dir=output.parent)
    os.close(fd)
    scratch = Path(scratch_name)
    cmd = [str(binary), 'generate', '--quiet',
           '--config', str(config_path(model)),
           '--voice', str(voice_file),
           '--text', text,
           '--output-path', str(scratch)]
    if quantize:
        cmd.append('--quantize')
    started = time.monotonic()
    try:
        with tempfile.TemporaryFile() as errors:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=errors, stderr=errors,
                                    env=_child_env(seed),
                                    startupinfo=_no_window_startupinfo())
            while True:
                try:
                    returncode = proc.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if cancel.is_set():
                        proc.kill()
                        proc.wait()
                        raise download.Cancelled()
            if returncode != 0:
                if _illegal_instruction(returncode):
                    raise UnsupportedCPU(
                        'This processor lacks the AVX2 and FMA instructions Pocket TTS needs '
                        '(Intel processors since 2013, AMD since 2015, but not every Celeron, '
                        'Pentium or Atom). Pick another voice engine.')
                errors.seek(0)
                tail = errors.read().decode('utf-8', 'replace').strip().splitlines()[-6:]
                raise EngineError(f'pocket-tts failed (exit {returncode}): '
                                  f'{" / ".join(tail) or "no output"}')
        with wave.open(str(scratch), 'rb') as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise EngineError(f'pocket-tts wrote {wav.getnchannels()} channels of '
                                  f'{8 * wav.getsampwidth()}-bit audio, expected 16-bit mono')
        if frames == 0:
            raise EngineError('pocket-tts wrote no audio')
        os.replace(scratch, output)
    finally:
        scratch.unlink(missing_ok=True)
    return Speech(output, frames / float(rate), rate, time.monotonic() - started)
