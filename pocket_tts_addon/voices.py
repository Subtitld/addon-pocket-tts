"""The models and the built-in voices the add-on offers.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

Models
------
Pocket TTS has one model per language. The project's language picks it; the
"Model" choice in Configure picks its size: standard (100M parameters), large
(Kyutai's 24-layer previews) or, for English only, small (18M). Every model is CC-BY-4.0, from
kyutai/pocket-tts-without-voice-cloning, the repository without the gated
voice cloning: the add-on speaks in built-in voices only.

Voices
------
Kyutai ships each built-in voice for every model, so any voice speaks any of
the seven languages, keeping something of its own accent. Of the 27, four are
left out: cosette (from Expresso) and jean (from EARS) are CC-BY-NC, which a
paid dub cannot use, and juergen and rafael name no source or licence. The
rest are CC0 or CC-BY-4.0; THIRD_PARTY_LICENSES/voices/README.md credits them.
"""

from __future__ import annotations

from dataclasses import dataclass

# The project's language (its primary subtag) -> Pocket TTS's language name.
LANGUAGES = {
    'en': 'english',
    'fr': 'french',
    'de': 'german',
    'pt': 'portuguese',
    'it': 'italian',
    'es': 'spanish',
    'nl': 'dutch',
}

# small: English only (Kyutai's 18M-parameter model, about twice as fast);
# the other languages have no small model and use their standard one.
SIZES = ('small', 'standard', 'large')
DEFAULT_SIZE = 'standard'


@dataclass(frozen=True)
class Model:
    id: str        # upstream's config name, pocket_tts/config/<id>.yaml
    language: str  # Pocket TTS's language name
    size: str      # one of SIZES


MODELS = tuple(
    [Model(name, name, 'standard') for name in LANGUAGES.values()]
    + [Model(f'{name}_24l', name, 'large') for name in LANGUAGES.values() if name != 'english']
    + [Model('english_2026-09_24l', 'english', 'large'),
       Model('english_18m_refl_2026-10', 'english', 'small')]
)
_BY_LANGUAGE_SIZE = {(m.language, m.size): m for m in MODELS}


def model_for(language: str, size: str) -> Model:
    size = size if size in SIZES else DEFAULT_SIZE
    return _BY_LANGUAGE_SIZE.get((language, size)) or _BY_LANGUAGE_SIZE[(language, DEFAULT_SIZE)]


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    woman: bool
    accent: str
    source: str   # where Kyutai took the recording from
    licence: str


VOICES = (
    Voice('alba', 'Alba', True, 'casual', 'Alba MacKenna (alba-mackenna/casual.wav)', 'CC-BY-4.0'),
    Voice('anna', 'Anna', True, 'British', 'VCTK p228', 'CC-BY-4.0'),
    Voice('azelma', 'Azelma', True, 'Canadian', 'VCTK p303', 'CC-BY-4.0'),
    Voice('caro_davy', 'Caro', True, 'audiobook reader', 'Voice-Zero (LibriVox)', 'CC0-1.0'),
    Voice('eponine', 'Eponine', True, 'Scottish', 'VCTK p262', 'CC-BY-4.0'),
    Voice('estelle', 'Estelle', True, 'French', 'Kyutai (unmute-prod-website/developpeuse-3.wav)', 'CC0-1.0'),
    Voice('eve', 'Eve', True, 'American', 'VCTK p361', 'CC-BY-4.0'),
    Voice('fantine', 'Fantine', True, 'British', 'VCTK p244', 'CC-BY-4.0'),
    Voice('jane', 'Jane', True, 'American', 'VCTK p339', 'CC-BY-4.0'),
    Voice('lola', 'Lola', True, 'Spanish', 'Common Voice (es)', 'CC0-1.0'),
    Voice('mary', 'Mary', True, 'American', 'VCTK p333', 'CC-BY-4.0'),
    Voice('vera', 'Vera', True, 'British', 'VCTK p229', 'CC-BY-4.0'),
    Voice('bill_boerst', 'Bill', False, 'audiobook reader', 'Voice-Zero (LibriVox)', 'CC0-1.0'),
    Voice('charles', 'Charles', False, 'British', 'VCTK p254', 'CC-BY-4.0'),
    Voice('daan', 'Daan', False, 'Dutch', 'CML-TTS (nl)', 'CC-BY-4.0'),
    Voice('george', 'George', False, 'American', 'VCTK p315', 'CC-BY-4.0'),
    Voice('giovanni', 'Giovanni', False, 'Italian', 'Common Voice (it)', 'CC0-1.0'),
    Voice('javert', 'Javert', False, 'deep', 'Unmute voice donation (Butter.wav)', 'CC0-1.0'),
    Voice('marius', 'Marius', False, 'soft', 'Unmute voice donation (Selfie.wav)', 'CC0-1.0'),
    Voice('michael', 'Michael', False, 'American', 'VCTK p360', 'CC-BY-4.0'),
    Voice('paul', 'Paul', False, 'British', 'VCTK p259', 'CC-BY-4.0'),
    Voice('peter_yearsley', 'Peter', False, 'audiobook reader', 'Voice-Zero (LibriVox)', 'CC0-1.0'),
    Voice('stuart_bell', 'Stuart', False, 'audiobook reader', 'Voice-Zero (LibriVox)', 'CC0-1.0'),
)
BY_ID = {voice.id: voice for voice in VOICES}

# Kyutai's own pick for each language, where it is one of the voices above.
DEFAULT_VOICE = {
    'english': 'alba', 'french': 'estelle', 'italian': 'giovanni', 'spanish': 'lola', 'dutch': 'daan',
}


def display_name(voice: Voice) -> str:
    return f'{voice.name} ({"woman" if voice.woman else "man"}, {voice.accent})'


def manifest_voices() -> list[dict]:
    """The voices as manifest.json and the hello frame list them: every one for every language."""
    return [{'id': voice.id, 'language': '*', 'display_name': display_name(voice), 'sample_rate': 24000}
            for voice in VOICES]
