# How small can the speech model get?

`compression_eval.py` takes the speech model (by default
`Abittee/amharic-speech-to-text-efa-v1`, about 2.4 GB) and tests smaller versions of it
on two public Amharic test sets (WAXAL and FLEURS). It tells you, for each version, how
big it would be and how many more mistakes it makes. This is groundwork for an iPhone
app, where the model has to be much smaller than 2.4 GB.

## The versions it tests

| Name | What it is | Rough size |
|---|---|---|
| `fp32` | The model as it is today (the yardstick) | ~2.4 GB |
| `fp16` | Every number stored with half the precision | ~1.2 GB |
| `int8` | The big layers stored as 8-bit whole numbers | ~0.70 GB |
| `pal6` | The big layers use only 64 distinct values each (6 bits) | ~0.57 GB |
| `pal4` | The big layers use only 16 distinct values each (4 bits) | ~0.44 GB |
| `int8-dynamic` | The 8-bit version the Windows app already uses for live preview | measured |

"The big layers" are the `nn.Linear` layers: 85 % of the weights. The rest (convolutions,
norms) is kept in fp16. Add `--include-conv` to compress the convolutions as well, as Apple's
tools would; that brings `pal4` down to ~0.30 GB.

`pal4` / `pal6` ("palettisation") is what Apple's Core ML tools offer for iPhone models.
The script only *simulates* the formats (it rounds the weights and runs them normally),
which is enough to see the accuracy cost before doing the real iPhone conversion.

## Run it in Google Colab

1. Open a new notebook, then **Runtime → Change runtime type → T4 GPU**.
2. Paste into a cell and run:

```python
!git clone https://github.com/endriasf/Amharic-Dictate
%cd Amharic-Dictate/tools
!pip install -q "transformers>=4.46" "datasets[audio]" soundfile librosa
```

3. If a dataset says you need to log in, run this and paste a Hugging Face token:

```python
from huggingface_hub import notebook_login; notebook_login()
```

4. Quick run first (first 500 clips of each test set):

```python
!python compression_eval.py --max-clips 500
```

5. When that works, the full run (takes a few hours, mostly the `int8-dynamic` row,
   which only runs on the CPU):

```python
!python compression_eval.py
```

   To skip the slow CPU row: `!python compression_eval.py --variants fp32 fp16 int8 pal6 pal4`

Results land in `compression_results/` (download them from the Colab file panel).

## Run it on the Windows PC

```
pip install torch "transformers>=4.46" "datasets[audio]" soundfile librosa
python tools/compression_eval.py --model Abittee/amharic-speech-to-text-efa-v1 --max-clips 500
```

Without an NVIDIA GPU this is slow; use `--max-clips 100` for a first look.

## Reading the results

The script prints a table and saves it as `compression_summary.md` / `.csv`:

- **Size (MB)** – about how much space the model's weights take in that format.
- **WER %** – out of 100 words, how many are wrong. **CER %** – the same for letters.
- **ΔWER pp** – how much worse than `fp32`, in percentage points. `+0.30` means 0.3 more
  wrong words per 100. Small negative numbers are just noise.

**Rule of thumb: pick the smallest version whose ΔWER stays within about 0.5 points on
both test sets.** The script prints that choice at the end. A quick `--max-clips 500` run
is noisy (differences under ~0.5 points can be chance), so confirm the winner with a full run.

`compression_per_clip.csv` has every sentence with what each version wrote, if you want to
see *which* words a smaller model gets wrong.

Notes:
- Mistakes on homophone letters (ሀ/ሐ/ኀ, ሰ/ሠ, አ/ዐ, ጸ/ፀ) and punctuation are not counted,
  same as `amharic_asr_benchmark.py`.
- The `fp32` numbers can differ slightly from the published 24.4 % WER (clip filtering and
  text clean-up differ a little). Compare versions against the `fp32` row, not the model card.
- `--palette-group-size 32` gives each block of 32 output channels its own palette (Core ML
  "per grouped channel"); a little bigger, usually more accurate at 4 bits.
- Model licence: CC BY-SA 4.0 — a shipped compressed copy keeps the same licence and attribution.
