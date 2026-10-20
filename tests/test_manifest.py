"""manifest.json, pins.json and the code agree with each other.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pocket_tts_addon import ADDON_ID, __version__, voices  # noqa: E402
from pocket_tts_addon.engine import pins  # noqa: E402

MANIFEST = json.loads((REPO_ROOT / 'manifest.json').read_text(encoding='utf-8'))
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_REVISION = re.compile(r'^[0-9a-f]{40}$')


def test_versions_agree():
    pyproject = tomllib.loads((REPO_ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    assert MANIFEST['version'] == __version__ == pyproject['project']['version']
    assert re.fullmatch(r'\d\d\.\d\d\.\d+', __version__), 'versions are YY.MM.N'
    assert MANIFEST['id'] == ADDON_ID


def test_manifest_lists_what_the_code_offers():
    assert MANIFEST['languages'] == list(voices.LANGUAGES)
    assert MANIFEST['voices'] == voices.manifest_voices()
    assert [m['id'] for m in MANIFEST['models']] == [m.id for m in voices.MODELS]
    assert MANIFEST['tasks'] == ['tts.synthesize']
    assert MANIFEST['voice_clone'] is False
    assert MANIFEST['compute'] == 'cpu'
    assert 'accelerators' not in MANIFEST


def test_model_choices_are_the_sizes():
    fields = {f['key']: f for f in MANIFEST['config_schema']['fields']}
    assert sorted(o['value'] for o in fields['model']['options']) == sorted(voices.SIZES)
    assert fields['model']['default'] == voices.DEFAULT_SIZE
    assert fields['quantize']['type'] == 'bool'


def test_every_language_has_a_model_for_every_size():
    for language in voices.LANGUAGES.values():
        for size in voices.SIZES:
            model = voices.model_for(language, size)
            assert model.language == language
    # Small is English only; the others fall back to their standard model.
    assert voices.model_for('english', 'small').id == 'english_18m_refl_2026-10'
    assert voices.model_for('french', 'small').id == 'french'
    assert voices.model_for('french', 'nonsense').id == 'french'


def test_left_out_voices_stay_out():
    # cosette and jean are CC-BY-NC; juergen and rafael name no licence.
    assert not {'cosette', 'jean', 'juergen', 'rafael'} & set(voices.BY_ID)
    assert all(v.licence in ('CC0-1.0', 'CC-BY-4.0') for v in voices.VOICES)
    assert set(voices.DEFAULT_VOICE.values()) <= set(voices.BY_ID)


def test_pins_cover_exactly_what_is_offered():
    data = pins()
    assert data['repo'] == 'kyutai/pocket-tts-without-voice-cloning'
    assert list(data['models']) == [m.id for m in voices.MODELS]
    for model_id, entry in data['models'].items():
        assert set(entry['voices']) == set(voices.BY_ID), model_id
        for pin in [entry['weights'], entry['tokenizer'], *entry['voices'].values()]:
            assert _SHA256.match(pin['sha256']), pin
            assert _REVISION.match(pin['revision']), pin
            assert pin['size'] > 0, pin
            assert pin['path'].startswith(f'languages/{model_id}/'), pin


def test_config_templates_name_only_local_files():
    for model_id, entry in pins()['models'].items():
        config = entry['config']
        assert '{weights}' in config and '{tokenizer}' in config, model_id
        assert 'hf://' not in config and 'kyutai/pocket-tts/' not in config, model_id
        assert config.count('weights_path:') - config.count('#weights_path:') == 1, model_id
