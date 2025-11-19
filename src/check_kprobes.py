#!/usr/bin/env python3
import os

print("Checking for available kernel functions...")

functions_to_check = [
    "__sock_sendmsg",
    "sock_sendmsg",
    "security_socket_sendmsg",
    "sock_sendmsg_nosec",
    "__sys_sendto",
    "__sys_sendmsg",
]

available_functions = []

try:
    with open("/proc/kallsyms", "r") as f:
        content = f.read()
        for func in functions_to_check:
            if f" {func}\n" in content or f" {func}\t" in content:
                print(f"[FOUND] {func}")
                available_functions.append(func)
            else:
                print(f"[MISSING] {func}")
except FileNotFoundError:
    print("[ERROR] /proc/kallsyms not found. Cannot verify kernel symbols.")
    exit(1)
except PermissionError:
    print("[ERROR] Permission denied reading /proc/kallsyms. Run as root.")
    exit(1)

if not available_functions:
    print("\n[WARN] None of the standard functions were found.")
else:
    print(f"\n[INFO] Available targets: {available_functions}")
