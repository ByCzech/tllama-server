# Debian source and runtime packages

The initial package set targets Debian 13 amd64. It contains:

- `tllama-server`: metapackage depending on the matching core and CPU packages.
- `tllama-server-core`: private server and common runtime libraries.
- `tllama-server-backend-cpu`: portable CPU variants and the OpenBLAS plugin.

All native components use the pinned fork revision in `cmake/NativeSource.cmake`.
The native gfx1250 fix is already part of that source; it is not reapplied by
quilt. This first package set does not build accelerator plugins.

## Source export and build

Apply and commit packaging changes before exporting. With an initialized
submodule and no tracked changes, run from the repository root:

```sh
python3 tools/make-orig.py
dpkg-checkbuilddeps
dpkg-source -b .
debuild -j"$(nproc)"
```

The exporter reads Git commits, not working files, and excludes `debian/` from
the orig archive. It embeds the pinned native sources, preserves symlinks and
executable modes, and normalizes timestamps and archive ownership. Existing
orig archives are accepted only if their contents are identical.
Packaging-only commits keep the native commit timestamp used in the archive,
so a Debian revision change can reuse the same orig archive. Manual root-level
`build*` and `stage*` directories are excluded from source diffs.

The `.dsc`, orig archive and Debian archive are sufficient to unpack and build
without Git or submodule initialization. CMake does not fetch UI assets or
native source dependencies. Use `apt-get build-dep .` to install build
dependencies from `debian/control`.

`DEBFULLNAME`, `DEBEMAIL`, signing keys and Git identity are not changed by
these scripts. The changelog and control file use the archive maintainer
contact. Future releases should update the changelog, native gitlink and native
metadata as appropriate before exporting a new source version.

## Private installation

The public command `/usr/bin/tllama-server` is a relative symlink to
`/usr/lib/tllama/server/tllama-server`. Shared libraries and CPU/BLAS plugins
reside in the same private directory and resolve common libraries through
`$ORIGIN`. No development headers, CLI tools, embedded web UI or system service
are installed. TLlama will manage individual server processes.

The backend package depends on exactly the same core package version. Private
SONAME metadata is used only during this build; these packages do not publish
global shlibs metadata or run ldconfig.

After component installation, the build copies the split runtime into a
temporary prefix, checks shared library resolution and verifies that the
server loads its CPU and OpenBLAS plugins there. This check does not run model
inference. It runs even when `DEB_BUILD_OPTIONS=nocheck` is used because it
validates the package installation layout.
