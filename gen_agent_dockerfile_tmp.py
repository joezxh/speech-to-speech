import re
from pathlib import Path

src = Path("Dockerfile.cu130").read_text(encoding="utf-8")
out = src

out = out.replace(
    "apt-get install -y --no-install-recommends python3.12-dev",
    "apt-get install -y --no-install-recommends python3.12-dev sox",
)
out = out.replace(
    "COPY src ./src",
    "COPY src ./src\n\n# Offline nltk data (avoid nltk.org SSRF hang).\n"
    "COPY cache/nltk_data /root/nltk_data\n"
    "RUN chmod -R 755 /root/nltk_data && chown -R root:root /root/nltk_data",
)
out = re.sub(
    r'RUN echo "\[build\] downloading nltk data.*?\|\| true',
    "# nltk data is baked in from cache/nltk_data above; no online download.",
    out,
    flags=re.DOTALL,
)
out = out.replace(
    "ENV UV_INDEX_STRATEGY=first-index",
    "ENV UV_INDEX_STRATEGY=first-index\nENV UV_NATIVE_TLS=true",
)
out = out.replace("uv sync --python", "uv sync --index-strategy unsafe-best-match --python")

Path("Dockerfile.agent").write_text(out, encoding="utf-8")
print("written", len(out), "bytes")
