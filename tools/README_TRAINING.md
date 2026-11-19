# Training your own Amharic model

Fine-tunes **facebook/w2v-bert-2.0** (MIT) on **WAXAL** + **FLEURS** Amharic (both CC-BY-4.0).
The result is a model you own: commercial use is allowed as long as you keep the
attribution the script writes into `final/README.md`.

## 1. Rent a GPU
Any one of these works. Pick a machine with a **24 GB+ NVIDIA GPU** (RTX 4090, L4, A10, A100)
and ~200 GB disk:
- RunPod / Vast.ai / Lambda: around $0.40–$2 per hour
- Google Colab Pro (A100): OK for the smoke test and short runs

## 2. Set up (Linux GPU machine)
```bash
python -m venv .venv && source .venv/bin/activate
pip install torch transformers>=4.46 datasets[audio] accelerate soundfile librosa
huggingface-cli login            # free HF account; accept dataset terms on the website if asked
```

## 3. Smoke test first (~5–10 min)
Checks that everything downloads and the training loop runs before you pay for hours.
```bash
python train_amharic_ctc.py --sources fleurs --max_train_samples 200 --max_steps 50 --output_dir smoke
```

## 4. Full training run
```bash
python train_amharic_ctc.py --sources waxal fleurs --output_dir am-w2vbert
```
- Expect several hours to roughly a day depending on the GPU and how much Amharic WAXAL has.
- Watch `eval_wer` in the log; it should fall steadily. The best checkpoint is kept automatically.
- Out of GPU memory? Use `--batch_size 8 --grad_accum 4`.
- Add your own recordings any time: `--sources waxal fleurs local:/path/to/clips`
  (same `clip.wav` + `clip.txt` layout as the benchmark).

## 5. Use it
1. Download `am-w2vbert/final/` to your PC (~2.3 GB).
2. Benchmark it against Ethio-ASR:
   `python amharic_asr_benchmark.py --data clips --models C:/path/final badrex/Ethio-ASR-amharic`
3. In the app's `config.json`, set `"model": "C:/path/final"`.

## Making it smaller
See [README_COMPRESSION.md](README_COMPRESSION.md): `compression_eval.py` measures how much
accuracy fp16, int8 and 4/6-bit versions of a model lose (groundwork for an iPhone app).

## Notes
- Output is unpunctuated Ethiopic words, which matches what the app expects today.
- `--normalize_homophones` trains on standardized spelling (ሀ/ሰ/አ/ጸ forms). This scores better,
  but users will always see the standardized spelling. Leave it off unless you want that.
- Licenses: keep `final/README.md` with the model. Before adding any other dataset, check that its
  license allows commercial use.
