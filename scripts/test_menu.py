#!/usr/bin/env python3
"""Smoke-test a packaged no-argument menu in a terminal; quit before USB access."""
import errno
import os
import pty
import select
import subprocess
import sys
import time

master, slave = pty.openpty()
process = subprocess.Popen([sys.argv[1]], stdin=slave, stdout=slave, stderr=slave)
os.close(slave)
output = bytearray()
try:
    os.write(master, b"q\n")
    deadline = time.monotonic() + 30
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError("Interactive menu timed out")
        ready, _, _ = select.select([master], [], [], 0.25)
        if ready:
            try:
                chunk = os.read(master, 4096)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                break
            if not chunk:
                break
            output.extend(chunk)
        elif process.poll() is not None:
            break
    if process.wait(timeout=5) != 0:
        raise RuntimeError(output.decode(errors="replace"))
    for text in (b"Enable USB volume and knob sync", b"Restore official firmware", b"Cancelled"):
        if text not in output:
            raise RuntimeError(f"Missing menu text {text!r}: {output!r}")
    print("Packaged interactive menu passed; cancelled before USB discovery.")
finally:
    os.close(master)
    if process.poll() is None:
        process.kill()
        process.wait()
