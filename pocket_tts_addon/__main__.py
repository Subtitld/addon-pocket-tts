"""Pocket TTS add-on for Subtitld — JSON-line protocol entry point.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy of
the License at http://www.apache.org/licenses/LICENSE-2.0. Unless required by
applicable law or agreed to in writing, software distributed under the License
is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.

What this add-on is
-------------------
Offline text-to-speech with Kyutai's Pocket TTS, in English, French, German,
Portuguese, Italian, Spanish and Dutch, at 24 kHz, in 23 built-in voices.
Serves `tts.synthesize`. Kyutai's standalone binary does the synthesis
(engine.py). Each language's model, about 220 MB, downloads on its first line
(download.py); after that nothing leaves the machine.

Wire format
-----------
One JSON object per line on stdin/stdout. Stderr is free-form logging, which
the host prefixes with `[addon:pocket-tts]` and surfaces.

Options (the host sets them from Configure as POCKET_TTS_<KEY>)
---------------------------------------------------------------
model: `standard`, or `large` for the bigger preview models; quantize: int8
weights, for less memory.

Limits
------
Built-in voices only: the voice cloning model is gated by Kyutai and is not
used. One line at a time. A cancel kills the line's process, or stops the
download (which resumes on the next request).
"""

from __future__ import annotations

import errno
import json
import logging
import os
import platform
import sys
import threading
import time
import traceback
from pathlib import Path

from pocket_tts_addon import ADDON_ID, PROTOCOL_VERSION, __version__
from pocket_tts_addon import download, engine, tls, voices

ADDON_VERSION = __version__

ERR_MODEL_MISSING = 'model_missing'
ERR_UNSUPPORTED_LANGUAGE = 'unsupported_language'
ERR_UNSUPPORTED_VOICE = 'unsupported_voice'
ERR_BAD_PARAMS = 'bad_params'
ERR_INTERNAL = 'internal'
ERR_CANCELLED = 'cancelled'
ERR_DISK_FULL = 'disk_full'
ERR_NETWORK = 'network_unavailable'

# No space left on the device, or over the user's disk quota.
_DISK_FULL_ERRNOS = {errno.ENOSPC, getattr(errno, 'EDQUOT', 122)}

_LANGUAGE_NAMES = {
    'english': 'English', 'french': 'French', 'german': 'German', 'portuguese': 'Portuguese',
    'italian': 'Italian', 'spanish': 'Spanish', 'dutch': 'Dutch',
}

log = logging.getLogger('pocket_tts_addon')


# ---------------------------------------------------------------------------
# stdio ownership + protocol frames
# ---------------------------------------------------------------------------
_PROTO_IN = None   # binary reader for host frames
_PROTO_OUT = None  # binary writer for our frames
_proto_lock = threading.Lock()


def _claim_protocol_stdio() -> None:
    """Give the protocol exclusive use of the real stdin/stdout.

    fd-level, not just `sys.stdout = sys.stderr`, so nothing else can write a
    stray line into the protocol. Falls back to the Python-level swap if the
    fd dance fails.
    """
    global _PROTO_IN, _PROTO_OUT
    try:
        sys.stdout.flush()
        in_fd = os.dup(0)
        out_fd = os.dup(1)
        devnull = os.open(os.devnull, os.O_RDONLY)
        try:
            os.dup2(devnull, 0)
        finally:
            os.close(devnull)
        os.dup2(2, 1)
        _PROTO_IN = os.fdopen(in_fd, 'rb')
        _PROTO_OUT = os.fdopen(out_fd, 'wb')
    except (OSError, ValueError, AttributeError):
        _PROTO_IN = sys.stdin.buffer
        _PROTO_OUT = sys.stdout.buffer
    sys.stdin = open(os.devnull, encoding='utf-8')  # stray input() -> EOFError
    sys.stdout = sys.stderr                        # stray print() -> the log


def _emit(frame: dict) -> None:
    data = (json.dumps(frame, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    out = _PROTO_OUT if _PROTO_OUT is not None else sys.stdout.buffer
    with _proto_lock:
        try:
            out.write(data)
            out.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass  # host went away; the frame loop exits on the next empty read


def _emit_progress(req_id: str, value: float, message: str = '') -> None:
    _emit({'id': req_id, 'type': 'progress',
           'value': max(0.0, min(1.0, float(value))), 'message': message})


def _emit_result(req_id: str, data: dict) -> None:
    _emit({'id': req_id, 'type': 'result', 'data': data})


def _emit_error(req_id: str, code: str, message: str, retryable: bool = False) -> None:
    _emit({'id': req_id, 'type': 'error', 'code': code,
           'message': message, 'retryable': retryable})


class _AddonError(Exception):
    """An expected failure that already knows its protocol code."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
def _env(*names: str) -> str:
    """First non-empty value among `names`, stripped. '' when none are set."""
    for name in names:
        value = (os.environ.get(name) or '').strip()
        if value:
            return value
    return ''


def _options() -> dict:
    size = _env('POCKET_TTS_MODEL').lower() or voices.DEFAULT_SIZE
    if size not in voices.SIZES:
        log.warning('POCKET_TTS_MODEL=%r is not one of %s; using %s', size, voices.SIZES, voices.DEFAULT_SIZE)
        size = voices.DEFAULT_SIZE
    return {
        'size': size,
        'quantize': _env('POCKET_TTS_QUANTIZE').lower() in ('1', 'true', 'yes', 'on'),
    }


def _resolve_language(raw) -> str:
    """Pocket TTS's language name for the host's tag (`pt-br`, `en_US`, `fr`)."""
    tag = str(raw or '').strip().lower().replace('_', '-')
    primary = tag.split('-', 1)[0]
    if primary in voices.LANGUAGES:
        return voices.LANGUAGES[primary]
    spoken = ', '.join(_LANGUAGE_NAMES[name] for name in voices.LANGUAGES.values())
    if not primary:
        raise _AddonError(ERR_UNSUPPORTED_LANGUAGE,
                          f"Set the project's language first: Pocket TTS speaks {spoken}.")
    raise _AddonError(ERR_UNSUPPORTED_LANGUAGE,
                      f'Pocket TTS does not speak {raw!r}. It speaks {spoken}; '
                      f'pick another voice engine for other languages.')


def _seed(params: dict) -> int:
    try:
        return int(params.get('seed', 42)) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return 42


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------
class _Request:
    def __init__(self, req_id: str):
        self.req_id = req_id
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None


_active: dict[str, _Request] = {}
_active_lock = threading.Lock()
_work_lock = threading.Lock()  # one line, or one download, at a time


def _megabytes(count: int) -> str:
    return f'{count / 1e6:,.0f} MB'


def _ensure_files(state: _Request, model: voices.Model, voice: str) -> None:
    pins = engine.files_for(model.id, voice)
    todo = download.missing(pins)
    if not todo:
        return
    total = sum(pin['size'] for pin in todo)
    what = (f'the {_LANGUAGE_NAMES[model.language]} model' if any(p is pins[0] for p in todo)
            else 'the voice')
    message = f'Downloading {what} ({_megabytes(total)})...'
    _emit_progress(state.req_id, 0.0, message)
    last = [0.0]

    def progress(done: int, total_bytes: int) -> None:
        now = time.monotonic()
        if now - last[0] >= 0.25 or done >= total_bytes:
            last[0] = now
            _emit_progress(state.req_id, 0.85 * done / max(1, total_bytes), message)

    started = time.monotonic()
    download.ensure(pins, engine.pins()['repo'], progress, state.cancel.is_set)
    log.info('downloaded %s for %s/%s in %.1fs', _megabytes(total), model.id, voice,
             time.monotonic() - started)


def _handle_synthesize(state: _Request, params: dict) -> None:
    req_id = state.req_id
    text = ' '.join(str(params.get('text') or '').split())
    output_path = params.get('output_path')
    if not text:
        _emit_error(req_id, ERR_BAD_PARAMS, 'text is empty')
        return
    if not isinstance(output_path, str) or not output_path.strip():
        _emit_error(req_id, ERR_BAD_PARAMS, 'output_path is required')
        return
    try:
        language = _resolve_language(params.get('language'))
    except _AddonError as exc:
        _emit_error(req_id, exc.code, exc.message)
        return
    voice_id = str(params.get('voice') or '') or voices.DEFAULT_VOICE.get(language, 'alba')
    if voice_id not in voices.BY_ID:
        _emit_error(req_id, ERR_UNSUPPORTED_VOICE, f'unknown voice {voice_id!r}')
        return
    options = _options()
    model = voices.model_for(language, options['size'])
    seed = _seed(params)

    outcome: tuple = ('error', ERR_INTERNAL, 'no outcome', False)
    try:
        if state.cancel.is_set():
            raise download.Cancelled()
        with _work_lock:
            _ensure_files(state, model, voice_id)
            if state.cancel.is_set():
                raise download.Cancelled()
            _emit_progress(req_id, 0.9, 'Speaking...')
            log.info('synthesize %s: model=%s voice=%s seed=%d quantize=%s chars=%d',
                     req_id, model.id, voice_id, seed, options['quantize'], len(text))
            speech = engine.synthesize(text, model.id, voice_id, Path(output_path), seed=seed,
                                       quantize=options['quantize'], cancel=state.cancel)
        log.info('synthesize %s: %.2fs of audio in %.2fs', req_id, speech.duration_sec, speech.seconds)
        outcome = ('result', {
            'path': output_path,
            'duration_sec': round(speech.duration_sec, 3),
            'sample_rate': speech.sample_rate,
            'channels': 1,
            'voice': voice_id,
        })
    except download.Cancelled:
        log.info('synthesize %s: cancelled', req_id)
        outcome = ('error', ERR_CANCELLED, 'cancelled', False)
    except download.DownloadError as exc:
        log.warning('synthesize %s: download failed: %s', req_id, exc)
        outcome = ('error', ERR_NETWORK, f'Could not download the model: {exc}', True)
    except engine.EngineError as exc:
        log.warning('synthesize %s failed: %s', req_id, exc)
        outcome = ('error', ERR_INTERNAL, str(exc), False)
    except OSError as exc:
        log.exception('synthesize %s failed', req_id)
        if getattr(exc, 'errno', None) in _DISK_FULL_ERRNOS:
            outcome = ('error', ERR_DISK_FULL, f'Out of disk space: {exc}', False)
        else:
            outcome = ('error', ERR_INTERNAL, f'{type(exc).__name__}: {exc}', False)
    except Exception as exc:  # noqa: BLE001 — every path must end in one terminal frame
        log.exception('synthesize %s failed', req_id)
        outcome = ('error', ERR_INTERNAL, f'{type(exc).__name__}: {exc}', False)

    if outcome[0] == 'result':
        _emit_progress(req_id, 1.0, '')
        _emit_result(req_id, outcome[1])
    else:
        _emit_error(req_id, *outcome[1:])


def _spawn(req_id: str, target, *args) -> None:
    state = _Request(req_id)
    with _active_lock:
        _active[req_id] = state

    def _run():
        try:
            target(state, *args)
        except BaseException:  # noqa: BLE001
            log.exception('worker crashed')
            tail = traceback.format_exc().strip().splitlines()[-1]
            _emit_error(req_id, ERR_INTERNAL, f'worker crashed: {tail}')
        finally:
            with _active_lock:
                _active.pop(req_id, None)

    thread = threading.Thread(target=_run, name=f'pocket-tts-{req_id}', daemon=True)
    state.thread = thread
    thread.start()


# ---------------------------------------------------------------------------
# Handshake + frame loop
# ---------------------------------------------------------------------------
def _send_hello() -> None:
    _emit({
        'type': 'hello',
        'protocol': PROTOCOL_VERSION,
        'addon': ADDON_ID,
        'version': ADDON_VERSION,
        'capabilities': [{
            'task': 'tts.synthesize',
            'languages': list(voices.LANGUAGES),
            'voices': voices.manifest_voices(),
            'voice_clone': False,
        }],
    })


def _read_frame() -> dict | None:
    source = _PROTO_IN if _PROTO_IN is not None else sys.stdin.buffer
    line = source.readline()
    if not line:
        return None  # stdin closed: the host went away
    text = line.decode('utf-8', errors='replace').strip().lstrip('﻿')
    if not text:
        return {}
    try:
        frame = json.loads(text)
    except ValueError as exc:
        log.warning('malformed frame %r: %s', line[:200], exc)
        return {}
    return frame if isinstance(frame, dict) else {}


def _main_loop() -> int:
    while True:
        frame = _read_frame()
        if frame is None:
            log.info('stdin closed; exiting')
            return 0
        if not frame:
            continue
        ftype = frame.get('type')

        if ftype == 'shutdown':
            log.info('shutdown requested')
            return 0

        if ftype == 'ready':
            log.info('handshake complete; host=%s host_version=%s',
                     frame.get('host'), frame.get('host_version'))
            continue

        if ftype == 'cancel':
            target = frame.get('target')
            with _active_lock:
                state = _active.get(target) if isinstance(target, str) else None
            if state is not None:
                log.info('cancel %s', target)
                state.cancel.set()
            continue

        if ftype == 'tts.synthesize':
            req_id = frame.get('id')
            params = frame.get('params')
            if not isinstance(req_id, str) or not req_id:
                log.warning('tts.synthesize without id')
                continue
            if params is None:
                params = {}
            if not isinstance(params, dict):
                _emit_error(req_id, ERR_BAD_PARAMS, 'params must be an object')
                continue
            _spawn(req_id, _handle_synthesize, params)
            continue

        # Unknown task: still answer, so the host's future resolves instead of
        # hanging until its timeout.
        req_id = frame.get('id')
        if isinstance(req_id, str) and req_id:
            _emit_error(req_id, ERR_BAD_PARAMS, f'unsupported frame type {ftype!r}')


def _stop_workers(budget_sec: float = 3.5) -> bool:
    """Cancel and join every worker. True when none is left running.

    The host allows 5 s between `shutdown` and SIGTERM, so stay under it.
    """
    with _active_lock:
        states = list(_active.values())
    for state in states:
        state.cancel.set()
    deadline = time.monotonic() + budget_sec
    for state in states:
        if state.thread is not None:
            state.thread.join(timeout=max(0.0, deadline - time.monotonic()))
    return not any(s.thread is not None and s.thread.is_alive() for s in states)


def _self_test() -> int:
    """Check what the frozen bundle needs, without the network or a model.

    The binary must be in the bundle and start; the pins and the TLS and
    hashing modules the downloads use must be there.
    """
    import hashlib
    import ssl
    import subprocess

    binary = engine.binary_path()
    engine.ensure_executable(binary)
    version = subprocess.run([str(binary), '--version'], capture_output=True, text=True,
                             timeout=60, env=engine._child_env(42)).stdout.strip()
    report = {
        'ok': bool(version),
        'version': ADDON_VERSION,
        'binary': version,
        'models': len(engine.pins()['models']),
        'openssl': ssl.OPENSSL_VERSION,
        'sha256': hashlib.sha256(b'').hexdigest()[:8],
        'ca_bundle': os.environ.get('SSL_CERT_FILE', ''),
    }
    print(json.dumps(report), file=sys.__stdout__, flush=True)
    return 0 if version else 1


def main() -> int:
    if '--version' in sys.argv[1:]:
        print(f'pocket-tts-addon {ADDON_VERSION}')
        return 0
    logging.basicConfig(
        level=(_env('POCKET_TTS_ADDON_LOG_LEVEL') or 'INFO').upper(),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        stream=sys.stderr,
    )
    tls.configure_ca_bundle()
    if '--self-test' in sys.argv[1:]:
        return _self_test()
    _claim_protocol_stdio()
    log.info('pocket-tts-addon %s on %s %s, python %s',
             ADDON_VERSION, platform.system(), platform.machine(), platform.python_version())
    if not engine.binary_path().is_file():
        # Not fatal: better to appear in the engine list and fail the first
        # request with a clear message than to vanish from the UI.
        log.warning('the pocket-tts binary is missing: %s', engine.binary_path())

    _send_hello()
    rc = 1
    try:
        rc = _main_loop()
    except KeyboardInterrupt:
        rc = 130
    except Exception:  # noqa: BLE001
        log.exception('main loop crashed')
        rc = 1
    finally:
        _stop_workers()
    return rc


if __name__ == '__main__':
    sys.exit(main())
