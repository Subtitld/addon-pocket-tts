# Pocket TTS models and voices

The add-on archive holds neither. Each language's model and each voice is
downloaded on first use, from the Hugging Face repository
[kyutai/pocket-tts-without-voice-cloning](https://huggingface.co/kyutai/pocket-tts-without-voice-cloning),
at the revisions `pocket_tts_addon/pins.json` names, each file checked by its
sha256.

## The models

Pocket TTS, by [Kyutai](https://kyutai.org), licensed under
[CC-BY-4.0](CC-BY-4.0.txt). The add-on uses the repository without voice
cloning; the cloning model, which Kyutai gates, is not used.

Kyutai forbids using Pocket TTS to imitate a person's voice without their
explicit, lawful consent, and for deceptive or harmful purposes.

## The voices

Each voice is a short embedding Kyutai computed from the recording named below.
The recordings' licences, from [kyutai/tts-voices](https://huggingface.co/kyutai/tts-voices):

| Voices | Recording | Licence |
|---|---|---|
| anna, azelma, charles, eponine, eve, fantine, george, jane, mary, michael, paul, vera | [CSTR VCTK Corpus](https://datashare.ed.ac.uk/handle/10283/3443), University of Edinburgh, speakers p228, p303, p254, p262, p361, p244, p315, p339, p333, p360, p259 and p229 | CC-BY-4.0 |
| alba | Alba MacKenna, "casual" | CC-BY-4.0 |
| daan | [CML-TTS](https://openslr.org/146/), Dutch | CC-BY-4.0 |
| bill_boerst, caro_davy, peter_yearsley, stuart_bell | [Voice-Zero](https://github.com/OwenTyme/voice-zero), from LibriVox | CC0-1.0 |
| javert, marius | Unmute Voice Donation Project (Butter, Selfie) | CC0-1.0 |
| estelle | Kyutai's own recording (unmute-prod-website/developpeuse-3.wav) | CC0-1.0 |
| giovanni, lola | Mozilla Common Voice, Italian and Spanish | CC0-1.0 |

Left out on purpose: cosette (Expresso) and jean (EARS), which are CC-BY-NC,
and juergen and rafael, whose recordings name no licence.
