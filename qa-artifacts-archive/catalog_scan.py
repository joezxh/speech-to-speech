# -*- coding: utf-8 -*-
"""一次性清点 parameter-catalog.yaml，供三处产物对齐用（用后即删）。"""
import sys
from collections import Counter, defaultdict

import yaml

PATH = r"D:\work\qwen-audio-agent\speech-to-speech-src\docs\parameter-catalog.yaml"
d = yaml.safe_load(open(PATH, encoding="utf-8"))
p = d["parameters"]
w = sys.stdout.write

w("schema=%s generated_from=%s at=%s\n" % (d.get("schema"), d.get("generated_from"), d.get("generated_at")))
w("total=%d\n\n" % len(p))

w("== (stage, backend) ==\n")
g = defaultdict(list)
for x in p:
    g[(x["stage"], x["backend"])].append(x["name"])
for k in sorted(g, key=lambda k: (k[0], k[1] or "")):
    w("%-9s %-14s %3d  %s\n" % (k[0], k[1] or "-", len(g[k]), ",".join(g[k])))
w("groups=%d\n\n" % len(g))

w("== type=fixed (%d) ==\n" % sum(1 for x in p if x["type"] == "fixed"))
for x in p:
    if x["type"] == "fixed":
        w("%s/%s/%s  exp=%s imp=%s src=%s\n" % (x["stage"], x["backend"] or "-", x["name"], x["exposure"], x["impact"], x["source_ref"]))
w("\n")

w("== effect in (hot, both) ==\n")
for x in p:
    if x["effect"] in ("hot", "both"):
        w("%-9s %-8s %-32s effect=%-5s impact=%-7s cost=%s\n" % (x["stage"], x["backend"] or "-", x["name"], x["effect"], x["impact"], x["change_cost"]))
w("\n")

w("== impact=container (%d) ==\n" % sum(1 for x in p if x["impact"] == "container"))
for x in p:
    if x["impact"] == "container":
        w("%s/%s/%s cost=%s exp=%s\n" % (x["stage"], x["backend"] or "-", x["name"], x["change_cost"], x["exposure"]))
w("\n")

w("== duplicate names ==\n")
by = defaultdict(list)
for x in p:
    by[x["name"]].append("%s/%s" % (x["stage"], x["backend"] or "-"))
for n, v in sorted(by.items()):
    if len(v) > 1:
        w("%-34s %s\n" % (n, " | ".join(v)))
w("distinct names=%d\n\n" % len(by))

w("== ops risk 前缀 ==\n")
w("%s\n" % Counter((x.get("risk") or "").split("：")[0] for x in p if x["exposure"] == "ops"))
w("ops_without_risk=%s\n\n" % [x["name"] for x in p if x["exposure"] == "ops" and not x.get("risk")])

w("== voice-ish ==\n")
KEY = ("speaker", "voice", "ref_", "instruct", "spk", "rvq", "prompt", "seed", "emotion", "style")
for x in p:
    if any(k in x["name"].lower() for k in KEY) and x["stage"] in ("tts", "llm", "runtime"):
        w("%-9s %-12s %-30s %-8s exp=%-8s effect=%s\n" % (x["stage"], x["backend"] or "-", x["name"], x["type"], x["exposure"], x["effect"]))
w("\n")

w("== ALL 196 ==\n")
for x in p:
    w("%s|%s|%s|%s|%s|%s|%s|%s\n" % (x["stage"], x["backend"] or "-", x["name"], x["type"], x["exposure"], x["effect"], x["impact"], x["change_cost"]))
