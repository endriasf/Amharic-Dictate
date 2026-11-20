"""Offline checks for compression_eval.py on tiny random models (no downloads).
Run:  python tools/test_compression_eval.py      (needs torch; the last check also needs transformers)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import torch

import compression_eval as ce

results = []


def check(name, cond):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name, flush=True)


torch.manual_seed(0)
w = torch.randn(64, 48)

# ---- fp16
f16 = ce.round_fp16(w)
check("fp16 keeps float32 dtype and shape", f16.dtype == torch.float32 and f16.shape == w.shape)
check("fp16 equals a real half round trip", torch.equal(f16, w.half().float()))

# ---- int8 per channel
q = ce.quant_int8_per_channel(w)
scale = w.abs().amax(dim=1, keepdim=True) / 127
check("int8 error <= half a step per row", bool(((q - w).abs() <= scale * 0.5 + 1e-3 * scale + 1e-7).all()))
check("int8 has <= 255 distinct values per row", max(len(torch.unique(r)) for r in q) <= 255)
check("int8 is idempotent-ish (re-quantising changes little)",
      (ce.quant_int8_per_channel(q) - q).abs().max().item() < scale.max().item())
zero = torch.zeros(4, 8)
check("int8 handles all-zero rows", torch.equal(ce.quant_int8_per_channel(zero), zero))

# ---- k-means
true = torch.tensor([-2.0, -0.5, 0.25, 3.0])
x = true[torch.randint(0, 4, (1, 5000))] + 0.001 * torch.randn(1, 5000)
c, labels = ce.kmeans_1d(x, 4)
check("k-means finds well-separated clusters", torch.allclose(c[0], true, atol=0.01))
check("k-means centroids sorted", bool((c[:, 1:] >= c[:, :-1]).all()))
check("k-means labels in range", int(labels.min()) >= 0 and int(labels.max()) <= 3)

# ---- palettisation
for bits in (4, 6):
    p = ce.palettize(w, bits)
    check(f"pal{bits}: <= {2 ** bits} distinct values per layer", len(torch.unique(p)) <= 2 ** bits)
    check(f"pal{bits}: shape kept", p.shape == w.shape)
pg = ce.palettize(w, 4, group_size=16)
check("pal4 grouped: <= 16 values per block of 16 rows",
      all(len(torch.unique(pg[i:i + 16])) <= 16 for i in range(0, 64, 16)))
err4 = (ce.palettize(w, 4) - w).pow(2).mean().item()
err6 = (ce.palettize(w, 6) - w).pow(2).mean().item()
err8 = (q - w).pow(2).mean().item()
check(f"error shrinks with bits (pal4 {err4:.2e} > pal6 {err6:.2e} > int8 {err8:.2e})", err4 > err6 > err8)
check("grouped palettes are at least as accurate", (pg - w).pow(2).mean().item() <= err4 * 1.01)
try:
    ce.palettize(w, 4, group_size=10)
    check("bad group size rejected", False)
except ValueError:
    check("bad group size rejected", True)


# ---- apply_variant on a tiny model: variants never stack, only Linear weights compressed
class Tiny(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = torch.nn.Conv1d(8, 32, 3)
        self.norm = torch.nn.LayerNorm(32)
        self.fc1 = torch.nn.Linear(32, 64)
        self.fc2 = torch.nn.Linear(64, 10)

    def forward(self, x):
        h = self.norm(self.conv(x).transpose(1, 2))
        return self.fc2(torch.relu(self.fc1(h)))


m = Tiny().eval()
params = dict(m.named_parameters())
base = {k: v.detach().clone() for k, v in params.items()}
lin = ce.linear_weight_names(m) & set(params)
check("Linear weights found", lin == {"fc1.weight", "fc2.weight"})
check("--include-conv adds Conv1d", ce.linear_weight_names(m, True) & set(params) == lin | {"conv.weight"})
xin = torch.randn(2, 8, 20)
y32 = m(xin)
outs = {}
for v in ["fp32", "fp16", "int8", "pal6", "pal4", "fp32"]:
    ce.apply_variant(m, base, v, lin, 0, 30, "cpu")
    outs[v] = m(xin).detach()
    if v == "pal4":
        check("pal4: fc1 has <= 16 values", len(torch.unique(m.fc1.weight)) <= 16)
        check("pal4: conv only fp16-rounded", torch.equal(m.conv.weight, base["conv.weight"].half().float()))
        check("pal4: biases fp16-rounded", torch.equal(m.fc1.bias, base["fc1.bias"].half().float()))
check("fp32 after other variants restores the original exactly", torch.equal(outs["fp32"], y32.detach()))
check("base copy untouched", all(torch.equal(base[k], params[k]) for k in base))
diffs = {v: (outs[v] - y32).abs().max().item() for v in ("fp16", "int8", "pal6", "pal4")}
check(f"output error ordered fp16 < int8 < pal4 ({diffs})", diffs["fp16"] < diffs["int8"] < diffs["pal4"])

# ---- size estimates
n = sum(p.numel() for p in params.values())
s32 = ce.estimated_bytes("fp32", params, lin, 0)
s16 = ce.estimated_bytes("fp16", params, lin, 0)
s8 = ce.estimated_bytes("int8", params, lin, 0)
s6 = ce.estimated_bytes("pal6", params, lin, 0)
s4 = ce.estimated_bytes("pal4", params, lin, 0)
check("fp32 size = 4 bytes/param", s32 == 4 * n)
check("fp16 size = 2 bytes/param", s16 == 2 * n)
check(f"sizes shrink fp32 > fp16 > int8 > pal6 > pal4 ({s32:.0f} {s16:.0f} {s8:.0f} {s6:.0f} {s4:.0f})",
      s32 > s16 > s8 > s6 > s4)
lin_n = sum(params[k].numel() for k in lin)
check("pal4 size formula", s4 == (n - lin_n) * 2 + lin_n * 0.5 + 2 * 16 * len(lin))

# ---- dynamic quantisation path (as in the app) and measured size
mq = torch.quantization.quantize_dynamic(Tiny().eval(), {torch.nn.Linear}, dtype=torch.qint8, inplace=True)
check("quantize_dynamic model runs", mq(xin).shape == y32.shape)
check("measured size > 0", ce.measured_bytes(mq) > 0)

# ---- end to end through main() with a tiny random w2v-BERT CTC model and fake test clips
try:
    import tempfile
    from pathlib import Path

    from transformers import (SeamlessM4TFeatureExtractor, Wav2Vec2BertConfig, Wav2Vec2BertForCTC,
                              Wav2Vec2BertProcessor, Wav2Vec2CTCTokenizer)
except ImportError as e:
    print("SKIP end-to-end (transformers not installed):", e)
else:
    import json
    tmp = Path(tempfile.mkdtemp())
    vocab = {c: i for i, c in enumerate("ሰላምአዲስ")}
    vocab.update({"|": len(vocab), "[UNK]": len(vocab) + 1, "[PAD]": len(vocab) + 2})
    (tmp / "vocab.json").write_text(json.dumps(vocab, ensure_ascii=False), encoding="utf-8")
    tok = Wav2Vec2CTCTokenizer(str(tmp / "vocab.json"), unk_token="[UNK]", pad_token="[PAD]", word_delimiter_token="|")
    proc = Wav2Vec2BertProcessor(feature_extractor=SeamlessM4TFeatureExtractor(), tokenizer=tok)
    cfg = Wav2Vec2BertConfig(hidden_size=32, num_hidden_layers=2, num_attention_heads=2, intermediate_size=64,
                             output_hidden_size=32, vocab_size=len(vocab), pad_token_id=vocab["[PAD]"],
                             add_adapter=True, num_adapter_layers=1, conv_depthwise_kernel_size=3)
    model_dir = tmp / "model"
    Wav2Vec2BertForCTC(cfg).save_pretrained(model_dir)
    proc.save_pretrained(model_dir)

    rng = np.random.default_rng(0)

    def fake_clips(spec, max_clips, min_s, max_s):
        return [{"id": f"{spec}-{i}", "ref": "ሰላም አዲስ", "ref_n": "ሰላም አዲስ",
                 "pcm": (rng.standard_normal(SRn) * 3000).astype(np.int16), "secs": 1.0}
                for i, SRn in enumerate([16000, 24000, 12000][: max_clips or 3])]

    ce.load_test_clips = fake_clips
    out = tmp / "out"
    sys.argv = ["compression_eval.py", "--model", str(model_dir), "--max-clips", "2", "--device", "cpu",
                "--out", str(out)]
    ce.main()
    md = (out / "compression_summary.md").read_text(encoding="utf-8")
    import csv
    rows = list(csv.DictReader(open(out / "compression_summary.csv", encoding="utf-8-sig")))
    check("summary has all 6 variants", [r["variant"] for r in rows] == ce.ALL_VARIANTS)
    check("fp32 delta is zero", float(rows[0]["waxal_wer_delta"]) == 0.0)
    check("markdown table written", md.count("\n|") >= 7)
    per = list(csv.DictReader(open(out / "compression_per_clip.csv", encoding="utf-8-sig")))
    check("per-clip rows = 6 variants x 2 datasets x 2 clips", len(per) == 24)

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
