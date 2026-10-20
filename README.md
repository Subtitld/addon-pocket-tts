# Pocket TTS add-on for Subtitld

Offline **text-to-speech** for [Subtitld](https://github.com/Subtitld/subtitld),
powered by [Pocket TTS](https://github.com/kyutai-labs/pocket-tts), the small
speech model from [Kyutai](https://kyutai.org), run by Kyutai's own standalone
binary.

- Serves the `tts.synthesize` task over Subtitld's add-on protocol.
- **Seven languages, 23 voices.** English, French, German, Portuguese,
  Italian, Spanish and Dutch, at 24 kHz. Every voice speaks every language.
- **CPU only, and fast.** About three times faster than real time on a laptop
  CPU, with about 660 MB of memory. No GPU, no torch, and no Python packages
  beyond the standard library.
- **Offline after the first line.** Each language's model, about 220 MB,
  downloads on its first line, then nothing leaves the machine: no telemetry,
  no account.
- **Built-in voices only.** Pocket TTS can also clone a voice, but Kyutai
  gates that model behind a Hugging Face login and terms of use, so the add-on
  does not offer it.

## Languages and models

The project's language picks the model. **Model** in Configure picks its size:

| Model | Languages | Download | Speed (i7-13700T) |
|-------|-----------|----------|-------------------|
| Standard (default) | all seven | 220 MB per language | about 3× real time |
| Small (18M parameters) | English; the others use Standard | 112 MB | about 7× real time |
| Large preview (24 layers) | all seven | 670 MB per language, 1.3 GB for English | about 1.2× real time |

Kyutai calls the large models previews, not their final models for those
languages. In a test with Whisper (two lines, three voices, French and
Portuguese) they made no fewer word errors than Standard. Listen before
dubbing a film with them.

A project in any other language is refused with a message that says so.

## Voices

| Women | Men |
|-------|-----|
| Alba (casual), Anna (British), Azelma (Canadian), Caro (audiobook reader), Eponine (Scottish), Estelle (French), Eve (American), Fantine (British), Jane (American), Lola (Spanish), Mary (American), Vera (British) | Bill (audiobook reader), Charles (British), Daan (Dutch), George (American), Giovanni (Italian), Javert (deep), Marius (soft), Michael (American), Paul (British), Peter (audiobook reader), Stuart (audiobook reader) |

A voice may keep something of its accent in another language, so listen to a
few in the project's language before choosing. Kyutai's own voices for French,
Italian, Spanish and Dutch are Estelle, Giovanni, Lola and Daan. Each voice
downloads on its first use, 0.3 to 8 MB.

Kyutai ships 27 voices. Four are left out: cosette and jean come from
recordings licensed for non-commercial use only (Expresso, EARS), which a
paid dub cannot use, and juergen and rafael name no source or licence.

## Options

Set these in **Settings ▸ Add-ons ▸ Pocket TTS ▸ Configure**.

| Option | Default | Env var | Notes |
|--------|---------|---------|-------|
| Model | Standard | `POCKET_TTS_MODEL` | `standard`, `small` or `large` (see above). |
| Use less memory | off | `POCKET_TTS_QUANTIZE` | 8-bit weights: 450 MB instead of 660 MB, about a fifth slower. |

Each line is spoken with the seed Subtitld sends, so the same line in the same
voice comes out the same every time. Subtitld stretches a dub to fit its
subtitle itself, so the add-on ignores the rate.

## What is bundled, what is downloaded

| File | Size | Licence | Source |
|------|------|---------|--------|
| `pocket-tts` (binary, bundled) | 25 MB | MIT | [kyutai-labs/pocket-tts v4.0.0](https://github.com/kyutai-labs/pocket-tts/releases/tag/v4.0.0), checked against the release's SHA256SUMS |
| Models and voices (downloaded) | see above | CC-BY-4.0; voices CC0 or CC-BY-4.0 | [kyutai/pocket-tts-without-voice-cloning](https://huggingface.co/kyutai/pocket-tts-without-voice-cloning) |

The downloads go to Subtitld's model folder (`$SUBTITLD_MODELS_DIR/pocket-tts`),
at the revisions in `pocket_tts_addon/pins.json`, each checked by its sha256.
An interrupted download resumes. `$HF_ENDPOINT` points them at a mirror.

The add-on gives the binary a config naming the downloaded files, so the
binary itself never goes to the network, and never sees a Hugging Face token.

The binary links about 400 Rust crates. Their licence texts are in
[THIRD_PARTY_LICENSES/pocket-tts/CRATES.txt](THIRD_PARTY_LICENSES/pocket-tts/CRATES.txt),
generated from the release's `Cargo.lock` by `tools/crate_licences.py`. Each
release archive also carries CPython and the native libraries its standard
modules need (OpenSSL, for the downloads, libffi, zlib), frozen by
PyInstaller; its `THIRD_PARTY_LICENSES/README.md` names the notice for every
native file, and the build fails if one has none. The voices' sources are
credited in [THIRD_PARTY_LICENSES/models](THIRD_PARTY_LICENSES/models/README.md).

Kyutai forbids using Pocket TTS to imitate someone's voice without their
explicit, lawful consent, or for deceptive or harmful purposes.

## Limits

- **x86 processors need AVX2 and FMA.** Kyutai builds the binary for
  x86-64-v3: Intel processors since 2013, AMD since 2015, but not every
  Celeron, Pentium or Atom. On a processor without them the first line fails
  with a message that says so.
- **Linux needs glibc 2.34 or newer** (Ubuntu 22.04, Debian 12, Fedora 35 and
  later), as Subtitld's own Linux builds do.
- **Platforms.** Releases ship Linux x86_64, macOS arm64 and Windows x86_64.
- **One line at a time.** A cancel stops the line at once, or stops the
  download, which resumes on the next line.

## Build

```bash
python tools/fetch_binary.py
pip install -e '.[build,dev]'
pyinstaller pyinstaller.spec --noconfirm
python tools/assemble_licences.py --bundle dist/pocket-tts-addon --out release-staging/THIRD_PARTY_LICENSES
pytest
```

To move to another Pocket TTS release, update `tools/fetch_binary.py`, then
run `tools/pin_models.py` and `tools/crate_licences.py` against a checkout of
that release.

A tag `vYY.MM.N` builds, tests and publishes every platform
(`.github/workflows/release.yml`).

## Licence

The add-on is Apache-2.0 ([LICENSE](LICENSE)). Pocket TTS is MIT, its models
are CC-BY-4.0, by Kyutai.
