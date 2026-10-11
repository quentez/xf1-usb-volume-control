"""Fail CI if vendor artifacts or personal debugging data enter tracked source."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {".fot", ".bin", ".exe", ".dll", ".dylib", ".so", ".apk", ".jsonl"}
paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
problems = []
for name in filter(None, paths):
    path = ROOT / name
    if path.suffix.lower() in FORBIDDEN:
        problems.append(name)
    if path.is_file():
        data = path.read_bytes()
        if b"/Users/" in data or b"BEGIN PRIVATE KEY" in data:
            # This audit's own literal checks are intentionally exempt.
            if name != "scripts/audit_source.py":
                problems.append(name)
if problems:
    raise SystemExit("Unexpected private/vendor artifacts: " + ", ".join(sorted(set(problems))))
print("Tracked source audit passed; no firmware, vendor binaries, or local logs.")
