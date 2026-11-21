"""
The speech model stored with 8-bit weights: about 600 MB on disk instead of 2.4 GB.

Every nn.Linear and nn.Conv1d weight is stored as int8 with one scale per output channel (symmetric,
range -127..127, scales rounded to float16). Everything else stays float32. When loading, the weights are
expanded back to float32, so the app runs exactly the "int8, Linear + Conv1d" variant measured by
tools/compression_eval.py: WAXAL test WER 23.54 % vs 23.49 % at full precision, FLEURS 15.88 % vs 15.84 %.

Memory use while dictating is unchanged (the model runs at full precision); only the download and the
disk space shrink.
"""
import os

INT8_FILE = "model.int8.safetensors"
SCALE_SUFFIX = ".int8_scale"
QMAX = 127


def quantized_weight_names(model):
    """The weights stored as int8: every nn.Linear and nn.Conv1d weight."""
    import torch
    kinds = (torch.nn.Linear, torch.nn.Conv1d)
    return {f"{name}.weight" for name, mod in model.named_modules() if isinstance(mod, kinds)}


def quantize(w):
    """float tensor -> (int8 tensor of the same shape, float16 scale per output channel)."""
    import torch
    w2 = w.to(torch.float32).reshape(w.shape[0], -1)
    scale = (w2.abs().amax(dim=1, keepdim=True) / QMAX).to(torch.float16).to(torch.float32)
    scale = torch.where(scale > 0, scale, torch.ones_like(scale))
    q = torch.clamp(torch.round(w2 / scale), -QMAX, QMAX).to(torch.int8)
    return q.reshape(w.shape).contiguous(), scale.reshape(-1).to(torch.float16).contiguous()


def dequantize(q, scale):
    """(int8 tensor, float16 scale per output channel) -> float32 tensor."""
    import torch
    w2 = q.to(torch.float32).reshape(q.shape[0], -1) * scale.to(torch.float32).reshape(-1, 1)
    return w2.reshape(q.shape)


def is_int8(model_path) -> bool:
    return os.path.isfile(os.path.join(str(model_path), INT8_FILE))


def load_state_dict(model_path):
    """Read the int8 weights file and return a full float32 state dict."""
    from safetensors.torch import load_file
    raw = load_file(os.path.join(str(model_path), INT8_FILE))
    out = {}
    for key in list(raw):
        if key.endswith(SCALE_SUFFIX):
            continue
        scale = raw.get(key + SCALE_SUFFIX)
        out[key] = dequantize(raw[key], scale) if scale is not None else raw[key]
        raw[key] = None                        # free each int8 tensor as soon as it's expanded
    return out


def load_ctc_model(model_path):
    """AutoModelForCTC.from_pretrained, also for a model folder with 8-bit weights."""
    from transformers import AutoModelForCTC
    if not is_int8(model_path):
        return AutoModelForCTC.from_pretrained(model_path)
    import torch
    from transformers import AutoConfig
    config = AutoConfig.from_pretrained(model_path)
    state = load_state_dict(model_path)
    model = None
    try:                                       # fast: build the model empty, then use the weights as they are
        with torch.device("meta"):
            model = AutoModelForCTC.from_config(config)
        model.load_state_dict(state, strict=True, assign=True)
        if any(t.is_meta for t in list(model.parameters()) + list(model.buffers())):
            model = None                       # something wasn't in the file: build it the normal way
    except Exception:
        model = None
    if model is None:
        model = AutoModelForCTC.from_config(config)
        model.load_state_dict(state, strict=True)
    return model.to(torch.float32)
