import os
import re
import sys

sys.path.insert(0, "src")
from speech_to_speech.config import load_config, resolve_config

for line in open("config/prod.env", encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)

r = resolve_config(load_config("config/prod.yaml"))
d = vars(r)
print("fields:", list(d)[:14])
for name, pipe in (d.get("pipelines") or {}).items():
    opts = getattr(pipe, "options", None) or (pipe.get("options") if isinstance(pipe, dict) else {})
    print("pipeline", name, {k: v for k, v in opts.items() if "diariz" in k})
print("alloc env =", os.environ.get("PYTORCH_CUDA_ALLOC_CONF"))
raw = str(d)
print("diar mentions:", re.findall(r"'diarization[a-z_]*': [^,}]+", raw)[:6])
