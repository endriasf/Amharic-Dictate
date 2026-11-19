# How small can the speech model get? (`compression_eval.py`)

The speech model (Abittee/amharic-speech-to-text-efa-v1) is about **2.4 GB** in float32. That is
too big for an iPhone app. This script tests smaller ways of storing the same model and measures
how much worse (or not) the dictation gets, on two public Amharic test sets: WAXAL and FLEURS.

It does not change the model or the app. It only measures.

## What it tests

| Variant | What it means | Size (about) |
|---|---|---|
| `fp32` | The original model (the yardstick) | 2.4 GB |
| `fp16` | Every number stored with half the precision | 1.2 GB |
| `int8` | Main layers stored as 8-bit whole numbers, one scale per row | ~0.7 GB |
| `int8-dynamic` | Exactly what the Windows app does for its live preview | ~0.8 GB |
| `pal6` | Main layers use a "palette" of 64 values per layer (6 bits each) | ~0.6 GB |
| `pal4` | The same with 16 values per layer (4 bits each), like Apple's Core ML palettisation | ~0.45 GB |

"Main layers" means the `Linear` layers, which hold nearly all of the model. Everything else is
stored as fp16. The script prints the real sizes for this model.

## Run it in Google Colab (easiest)

1. Open https://colab.research.google.com, create a new notebook.
2. Menu **Runtime → Change runtime type → T4 GPU**.
3. Paste these into cells and run them one after another:

```
!git clone https://github.com/endriasf/amharic-dictate
%cd amharic-dictate
!pip install -q "transformers>=4.46" "datasets[audio]" soundfile librosa accelerate
```
```
from huggingface_hub import notebook_login; notebook_login()
```
(paste a free Hugging Face "read" token; if a dataset page asks you to accept its terms, accept them on the website)
```
!python tools/compression_eval.py --model Abittee/amharic-speech-to-text-efa-v1 --max-clips 500
```

`--max-clips 500` is a quick run (500 random clips from each test set, roughly 30–60 minutes,
most of it the `int8-dynamic` variant, which runs on the CPU just like the app).
For the final numbers, run without `--max-clips` (the whole test sets, several hours). To skip the slow
CPU variant: `--variants fp32 fp16 int8 pal6 pal4`.

Download the results from the file panel on the left: `compression_results/compression_results.md`.

## Run it on the Windows PC

In the repo folder, with the app's Python:
```
pip install "transformers>=4.46" "datasets[audio]" soundfile librosa accelerate
huggingface-cli login
python tools/compression_eval.py --model Abittee/amharic-speech-to-text-efa-v1 --max-clips 500
```
Without an NVIDIA GPU this is slow; use a small `--max-clips` (e.g. 100) or Colab.

To check the script itself without downloading anything: `python tools/compression_eval.py --self-test`.

## How to read the results

The table has, per variant: the size, and the WER (word error rate) and CER (letter error rate)
on each test set, plus **Δ**, the change versus `fp32` in percentage points. A Δ WER of `+0.3` means
3 more wrong words per 1000.

**Pick the smallest variant whose WER stays within about 0.5 points of `fp32` on both test sets.**
The script prints that choice at the end ("Recommendation").

- Δ of a few tenths up or down is noise, especially with `--max-clips`.
- If `pal4` loses more than 0.5 points, try `--palette-group-size 16` (a separate palette for every
  16 rows: a few MB bigger, usually more accurate), or settle for `pal6`.
- `--also-conv` also shrinks the model's convolution layers (~75 M more numbers); use it to see the
  smallest realistic size.

## Notes

- Scoring uses the same text rules as `amharic_asr_benchmark.py` (homophone letters such as ሀ/ሐ/ኀ and
  punctuation do not count as errors), and the same test data loading as `train_amharic_ctc.py`
  (clips 0.5–20 s). Because the homophone letters are not counted, the fp32 numbers can come out a bit
  lower than the model card's (WAXAL WER 24.4 %, CER 9.6 %). The comparison between variants is what
  matters.
- Decoding is greedy (no dictionary, no language model), like the published numbers.
- The int8 and palette variants are simulated: the weights are rounded to the smaller format and back,
  so the accuracy is what the small file would give. The real iPhone file would be made later with
  Apple's coremltools.
- If FLEURS fails to load (newer `datasets` versions dropped loading scripts), run with `--datasets waxal`.
- `per_clip.csv` lists every clip with the reference and each variant's transcript, to see *what* goes wrong.
