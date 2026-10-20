import sys, traceback

sys.path.insert(0, "/opt/cosyvoice-src")
print("PYTHONPATH pieces:")
for p in sys.path:
    print("  ", p)
try:
    import cosyvoice

    print("IMPORT cosyvoice OK ->", cosyvoice.__file__)
except Exception:
    print("IMPORT cosyvoice FAILED:")
    traceback.print_exc()
    sys.exit(0)

try:
    from cosyvoice.cli.cosyvoice import CosyVoice2

    print("IMPORT CosyVoice2 OK")
except Exception:
    print("IMPORT CosyVoice2 FAILED:")
    traceback.print_exc()
