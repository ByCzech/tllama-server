#!/usr/bin/env python3
"""Check the split runtime in a temporary, relocated installation tree."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: check-runtime.py CORE_PACKAGE_TREE CPU_PACKAGE_TREE")
    with tempfile.TemporaryDirectory(prefix="tllama-debian-check-") as temporary:
        root = Path(temporary)
        for tree in sys.argv[1:]:
            shutil.copytree(Path(tree) / "usr", root / "usr", symlinks=True, dirs_exist_ok=True)
        runtime = root / "usr/lib/tllama/server"
        server = runtime / "tllama-server"
        environment = os.environ.copy()
        for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "GGML_BACKEND_PATH", "GGML_BACKEND_DL_PATH"):
            environment.pop(key, None)
        environment["LC_ALL"] = "C"
        for binary in [runtime / "tllama-server", *runtime.glob("*.so*")]:
            if binary.is_symlink():
                continue
            result = subprocess.run(
                ["ldd", str(binary)], env=environment, cwd=root,
                text=True, capture_output=True, check=True)
            if "not found" in result.stdout + result.stderr:
                raise RuntimeError(f"Unresolved dependency of {binary}:\n{result.stdout}{result.stderr}")
            for line in result.stdout.splitlines():
                if re.match(r"\s*lib(?:ggml|llama|mtmd)[^ ]*\s+=>", line):
                    if str(runtime) + "/" not in line:
                        raise RuntimeError(f"Private library resolved outside the staged runtime: {line}")
        metadata = (Path(__file__).resolve().parents[1] / "cmake/NativeSource.cmake").read_text()
        revision = re.search(r'set\(TLLAMA_LLAMA_REVISION "([0-9a-f]{40})"\)', metadata).group(1)
        build = re.search(r'set\(TLLAMA_LLAMA_BUILD_NUMBER ([0-9]+)\)', metadata).group(1)
        version = subprocess.run([str(server), "--version"], env=environment, cwd=root,
                                 text=True, capture_output=True, check=True)
        expected = f"(build {build}, commit {revision[:10]})"
        if expected not in version.stdout + version.stderr:
            raise RuntimeError(f"Staged server does not match the pinned native fingerprint {expected}:\n"
                               f"{version.stdout}{version.stderr}")
        print(version.stdout + version.stderr, end="")
        result = subprocess.run(
            [str(server), "--log-verbosity", "5", "--list-devices"],
            env=environment, cwd=root, text=True, capture_output=True, check=True)
        output = result.stdout + result.stderr
        print(output, end="")
        if not any("loaded CPU backend from " + str(runtime) + "/" in line
                   for line in output.splitlines()):
            raise RuntimeError("The relocated server did not load a staged CPU backend")
        if not any("loaded BLAS backend from " + str(runtime) + "/" in line
                   for line in output.splitlines()):
            raise RuntimeError("The relocated server did not load the staged BLAS backend")
        print("Relocated split CPU/OpenBLAS runtime check passed")


if __name__ == "__main__":
    main()
