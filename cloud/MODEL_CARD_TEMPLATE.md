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

# Amharic Speech-to-Text EFA v1

Amharic speech-to-text model (CTC) used by **Amharic Dictate**, an offline Amharic dictation app for Windows.

**Trained by Endrias F. Abitte**, 2026.

## Results
<!-- filled in from the training log / comparison -->
Raw model output (greedy CTC decoding, no dictionary or language model):

| Test set | Clips | Hours | Word error rate | Character error rate |
|---|---|---|---|---|
| WAXAL + FLEURS Amharic test | 3,536 | 15.4 | 24.4% | 9.6% |
| WAXAL + FLEURS Amharic validation | 714 | 3.2 | 20.6% | 7.6% |

Training: 3 epochs on 33,566 clips (154 hours), one RTX 5090, about 2 hours.

## Training data and credits
- Base model: [facebook/w2v-bert-2.0](https://huggingface.co/facebook/w2v-bert-2.0) — MIT licence, © Meta.
- [WAXAL](https://huggingface.co/datasets/google/WaxalNLP) Amharic ASR (amh_asr) — Google Research and partners;
  Amharic recordings by Digital Umuganda, CC BY-SA 4.0.
- [FLEURS](https://huggingface.co/datasets/google/fleurs) Amharic (am_et) — Google, CC BY 4.0.

## Licence
CC BY-SA 4.0. You may use, share and adapt this model, including commercially, if you credit
**Endrias F. Abitte** and share adaptations under the same licence.

## How to cite
Endrias F. Abitte (2026). *Amharic Speech-to-Text EFA v1* [speech recognition model]. Hugging Face.
