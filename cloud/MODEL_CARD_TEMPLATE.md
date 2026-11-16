---
language: am
license: cc-by-sa-4.0
base_model: facebook/w2v-bert-2.0
datasets:
  - google/WaxalNLP
  - google/fleurs
tags:
  - automatic-speech-recognition
  - amharic
  - ctc
pipeline_tag: automatic-speech-recognition
---

# Amharic Dictate ASR v1

Amharic speech-to-text model (CTC) used by **Amharic Dictate**, an offline Amharic dictation app for Windows.

**Trained by Endrias F. Abitte**, 2026.

## Results
<!-- filled in from the training log / comparison -->
| Test set | Word error rate | Character error rate |
|---|---|---|
| FLEURS Amharic test | – | – |

## Training data and credits
- Base model: [facebook/w2v-bert-2.0](https://huggingface.co/facebook/w2v-bert-2.0) — MIT licence, © Meta.
- [WAXAL](https://huggingface.co/datasets/google/WaxalNLP) Amharic ASR (amh_asr) — Google Research and partners;
  Amharic recordings by Digital Umuganda, CC BY-SA 4.0.
- [FLEURS](https://huggingface.co/datasets/google/fleurs) Amharic (am_et) — Google, CC BY 4.0.

## Licence
CC BY-SA 4.0. You may use, share and adapt this model, including commercially, if you credit
**Endrias F. Abitte** and share adaptations under the same licence.

## How to cite
Endrias F. Abitte (2026). *Amharic Dictate ASR v1* [speech recognition model]. Hugging Face.
