#!/usr/bin/env python3
"""Export committed outer and native sources as a reproducible Debian orig tar."""

import argparse
import io
import lzma
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile


def git(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        help="destination directory (default: parent of the repository)")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    native = root / "vendor/llama.cpp"
    if git(root, "status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit("Commit or stash tracked changes before exporting sources")
    metadata = git(root, "show", "HEAD:cmake/NativeSource.cmake").decode()
    match = re.search(r'set\(TLLAMA_LLAMA_REVISION "([0-9a-f]{40})"\)', metadata)
    if not match:
        raise SystemExit("Cannot read the pinned native revision")
    revision = match.group(1)
    gitlink = git(root, "rev-parse", "HEAD:vendor/llama.cpp").decode().strip()
    if gitlink != revision or git(native, "rev-parse", "HEAD").decode().strip() != revision:
        raise SystemExit("Native checkout, gitlink and NativeSource.cmake must identify the same commit")
    if git(native, "status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit("Commit or stash tracked native changes before exporting sources")
    if any(line.startswith(b"160000 ") for line in git(native, "ls-tree", "-r", revision).splitlines()):
        raise SystemExit("Native source has nested submodules; extend the exporter before releasing it")
    source = subprocess.check_output(
        ["dpkg-parsechangelog", "--show-field", "Source"], cwd=root, text=True).strip()
    version = subprocess.check_output(
        ["dpkg-parsechangelog", "--show-field", "Version"], cwd=root, text=True).strip()
    upstream_version = version.split(":", 1)[-1].rsplit("-", 1)[0]
    prefix = f"{source}-{upstream_version}"
    # Packaging-only revisions must not change the orig archive timestamps.
    epoch = int(git(native, "show", "-s", "--format=%ct", revision))
    entries = {}
    for repository, commit, destination in ((root, "HEAD", ""), (native, revision, "vendor/llama.cpp/")):
        archive_bytes = git(repository, "archive", "--format=tar", commit)
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                if not destination and path.parts[0] == "debian":
                    continue
                if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir() or member.issym()):
                    raise SystemExit(f"Unsupported archive entry: {member.name}")
                data = archive.extractfile(member).read() if member.isfile() else None
                member.name = prefix + "/" + destination + member.name
                member.uid = member.gid = 0
                member.uname = member.gname = ""
                member.mtime = epoch
                member.pax_headers = {}
                entries[member.name] = (member, data)
    destination = (arguments.output_dir or root.parent).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{source}_{upstream_version}.orig.tar.xz"
    # Write atomically and leave a previously exported archive untouched.
    with tempfile.NamedTemporaryFile(dir=destination, suffix=".orig-tmp", delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with lzma.open(temporary_path, "wb", preset=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                for name in sorted(entries):
                    member, data = entries[name]
                    archive.addfile(member, io.BytesIO(data) if data is not None else None)
        if output.exists():
            if output.read_bytes() != temporary_path.read_bytes():
                raise SystemExit(f"Existing archive has different contents: {output}; use a new source version")
        else:
            temporary_path.chmod(0o644)
            temporary_path.replace(output)
    finally:
        temporary_path.unlink(missing_ok=True)
    print(output)


if __name__ == "__main__":
    main()
