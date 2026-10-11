# tllama-server

Distribution and build integration for a pinned, patched llama.cpp server.
The initial build supports Linux. Debian packaging and Python distribution
metadata will be added separately.

## Sources

`vendor/llama.cpp` is pinned to an exact commit. `cmake/NativeSource.cmake`
records that revision and its upstream base build number for reproducible
version information, including builds from source archives without Git.
Update the gitlink and this metadata together when changing native revisions.

```sh
git submodule update --init --recursive
```

Source release archives must include the actual submodule files, not just the
gitlink. Builds do not fetch native sources or web UI assets.

## CPU build and staged installation

Requirements: CMake 3.21+, a C/C++ compiler, Ninja, and OpenSSL development
files for the default HTTPS support. OpenMP is used when available.

```sh
cmake -S . -B build-cpu -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr
cmake --build build-cpu --target tllama-runtime -j"$(nproc)"
DESTDIR="$PWD/stage-cpu" cmake --install build-cpu
stage-cpu/usr/bin/tllama-server --version
```

The default build includes the CPU variants supported by upstream's current
architecture detection. On x86 this includes a baseline x64 variant. Only the
server, its runtime dependencies and configured backend modules are built.
Other upstream tool targets are configured but are not part of the build or
installation. The embedded web UI is disabled; HTTPS and multimodal support
are retained.

The installed layout is:

- `bin/tllama-server`: a relative symlink to the private executable.
- `lib/tllama/server/tllama-server`: the native executable.
- `lib/tllama/server/`: the required shared libraries and backend modules.
- `share/doc/tllama-server/LICENSE.llama.cpp`: the native license.

Private libraries use relative `$ORIGIN` lookup. The native loader discovers
default backend modules beside the real executable, including when launched
through the public symlink. The staged tree can be moved without relying on
the build directory, `LD_LIBRARY_PATH`, or a system-wide `ldconfig` entry.

## Backend builds and install components

Native `GGML_*` backend options and SDK/compiler settings are passed directly
to CMake. Use separate build directories for different SDK versions.

- `TLLAMA_BUILD_SERVER=OFF` builds backend modules without compiling the server.
- `GGML_CPU=OFF` disables CPU modules, including the CPU variant collection,
  for independent accelerator builds.
- `TLLAMA_BACKEND_INSTALL_DIR` selects a relative destination for modules;
  the default is the private runtime directory.
- `TLLAMA_BACKEND_RPATH` adds SDK runtime directories to the modules' relative
  search paths without adding those SDK paths to the common runtime.
- `tllama-backend-<api>` builds the selected API's backend targets.
- Install component `core` contains the executable and common runtime.
- Install component `backend-<api>` contains that API's modules; all CPU variants
  belong to `backend-cpu`. HIP uses `backend-hip`.

For example, install only the CPU modules into a package staging directory:

```sh
DESTDIR="$PWD/stage-cpu-backend" \
    cmake --install build-cpu --component backend-cpu
```

Modules installed into a separate backend directory are not automatically
selected by the launcher. Backend selection and SDK-version alternatives will
be added with packaging. Every backend package must depend on the exact matching
core package version; internal ggml module ABI compatibility is not assumed.
