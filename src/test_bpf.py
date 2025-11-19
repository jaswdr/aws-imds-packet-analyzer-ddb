#!/usr/bin/env python3
from bcc import BPF
import os
import sys

print("Attempting to compile BPF module...")

src_file = "src/bpf.c"
if not os.path.exists(src_file):
    print(f"Error: {src_file} not found.")
    sys.exit(1)

try:
    # First try with default settings
    b = BPF(src_file=src_file)
    print("Success! BPF module compiled.")
except Exception as e:
    print("\n[ERROR] Compilation Failed. Retrying with debug output (DEBUG=4)...\n")
    try:
        # Retry with debug output to show clang errors
        b = BPF(src_file=src_file, debug=4)
    except Exception as e_debug:
        print(f"\n[FATAL] BPF Compilation Error:\n{e_debug}")
