# Building Debian packages

The initial package set targets Debian 13 amd64. It contains:

- `tllama-server`: metapackage depending on the matching core and CPU packages.
- `tllama-server-core`: private server and common runtime libraries.
- `tllama-server-backend-cpu`: portable CPU variants and the OpenBLAS plugin.
- `tllama-server-backend-vulkan`: the Vulkan compute plugin, with dependencies
  on the exactly matching core and CPU packages.
- `tllama-server-backend-rocm10.1`: the optional ROCm 10.1 HIP plugin.
- `tllama-server-backend-cuda12.4`: the optional Debian CUDA 12.4 plugin.
- `tllama-server-backend-cuda12.9`: the optional NVIDIA CUDA 12.9 plugin.
- `tllama-server-backend-cuda13.3`: the optional NVIDIA CUDA 13.3 plugin.
- `tllama-server-backend-sycl`: the optional Intel oneAPI SYCL plugin.

All native components use the pinned fork revision in `cmake/NativeSource.cmake`.
The native gfx1250 fix is already part of that source; it is not reapplied by
quilt. The Debian version follows the native release series: this pinned
development snapshot uses `0.6.0~dev+b11552`, with a Debian revision appended.

## Source export and build

Apply and commit packaging changes before exporting. With an initialized
submodule and no tracked changes, run from the repository root:

```sh
python3 tools/make-orig.py
dpkg-checkbuilddeps -Ppkg.tllama-server.cpu-only
dpkg-source -b .
debuild -Ppkg.tllama-server.cpu-only -j"$(nproc)"
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

## Build profiles

Without a profile, the build produces the four CPU/Vulkan packages. ROCm, CUDA and
SYCL are built explicitly with their own profiles. Profiles select the
package set, build dependencies and native CMake targets:

- `pkg.tllama-server.cpu-only`: metapackage, core and CPU/OpenBLAS in
  `build-debian`. Vulkan development dependencies are not required.
- `pkg.tllama-server.vulkan-only`: only the Vulkan package in
  `build-debian-vulkan`. OpenSSL/OpenBLAS development dependencies are not
  required, and neither the server nor CPU plugins are compiled.

- `pkg.tllama-server.rocm-only`: only the ROCm 10.1 package in
  `build-debian-rocm10.1`, using TheRock under `/opt/rocm/core-10.1`.
  The build requires `amdrocm-core-sdk10.1` and conflicts with the legacy
  `libamdhip64-dev` headers. CPU/Vulkan/OpenSSL/OpenBLAS development packages
  are not required by this profile.

The profiles cannot be combined. Once the matching core and CPU packages are
built, build the Vulkan package independently:

```sh
dpkg-checkbuilddeps -Ppkg.tllama-server.vulkan-only
debuild -Ppkg.tllama-server.vulkan-only -j"$(nproc)"
```

Each profile's clean step removes its own CMake tree. CPU-only builds do not
remove the Vulkan tree, and Vulkan-only builds do not remove the CPU tree.
The Vulkan build uses a temporary ggml-base from its own build tree for linking
and dependency inspection; only the Vulkan module goes into the plugin package.
The matching core package supplies ggml-base at runtime.

## Private installation

The executable is `/usr/lib/tllama/server/tllama-server`; no command or symlink
is installed in `/usr/bin`. Shared libraries and CPU/BLAS/Vulkan plugins
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
Vulkan device discovery and inference are checked manually on the target
machine; the package build does not require a working GPU or Vulkan driver.

## ROCm package

```sh
dpkg-checkbuilddeps -Ppkg.tllama-server.rocm-only
debuild -Ppkg.tllama-server.rocm-only -j"$(nproc)"
```

The SDK's HIP compiler, bitcode and CMake packages are selected explicitly.
The installed module is
`/usr/lib/tllama/server/backends/rocm10.1/libggml-hip.so`.
The `tllama-server-rocm` alternatives group supplies the default loader link at
`/usr/lib/tllama/server/libggml-hip.so`. The module resolves common libraries
relative to its own location and ROCm libraries from the versioned SDK prefix.
Runtime dependencies on `amdrocm-runtime10.1` and `amdrocm-blas10.1` are declared
explicitly because AMD's packages do not consistently provide shlibs metadata.

Package changes contained within `debian/` can reuse the existing orig archive.
The source-only build guide is not installed in the user-facing package docs.

## CUDA 12.4 package

```sh
dpkg-checkbuilddeps -Ppkg.tllama-server.cuda12.4-only
debuild -Ppkg.tllama-server.cuda12.4-only -j"$(nproc)"
```

This profile builds only the CUDA package in `build-debian-cuda12.4`, using
`nvidia-cuda-toolkit` and `/usr/bin/nvcc` from Debian 13. It cannot be combined
with another tllama-server profile. CUDA graphs are enabled and NCCL is disabled.
The architecture list is independent of GPUs present on the build machine and
includes a native/virtual sm_60 image for Pascal P100 FP16 support.

The installed module is
`/usr/lib/tllama/server/backends/cuda12.4/libggml-cuda.so`.
The `tllama-server-cuda` alternatives group supplies the default loader link at
`/usr/lib/tllama/server/libggml-cuda.so`. Common libraries are resolved relative
to the module, while CUDA runtime libraries use Debian's system library paths.
Shared library metadata supplies dependencies on the CUDA runtime and NVIDIA
driver packages. A real NVIDIA GPU is not required for building the package.

## CUDA 12.9 package

```sh
dpkg-checkbuilddeps -Ppkg.tllama-server.cuda12.9-only
debuild -Ppkg.tllama-server.cuda12.9-only -j"$(nproc)"
```

This profile builds only the CUDA 12.9 package in `build-debian-cuda12.9`, using
`cuda-toolkit-12-9` under `/usr/local/cuda-12.9`. It keeps Pascal support and
adds architecture-specific Blackwell images for sm_120a and sm_121a.

The build makes a private SDK shadow under `build-cuda12.9-sdk` and adds
the glibc 2.41 exception specifications to four math declarations in its copy
of `math_functions.h`. NVIDIA-owned files remain untouched. The shadow is
excluded from Git and source archives and removed when cleaning this profile.

The plugin is installed under `backends/cuda12.9` and participates in the same
`tllama-server-cuda` alternatives group as CUDA 12.4, with a higher priority.
Its runtime paths point to the real versioned SDK library directory, never to
the build-local shadow. Runtime and cuBLAS package dependencies are explicit.

## CUDA 13.3 package

```sh
dpkg-checkbuilddeps -Ppkg.tllama-server.cuda13.3-only
debuild -Ppkg.tllama-server.cuda13.3-only -j"$(nproc)"
```

This profile builds only the CUDA 13.3 package in `build-debian-cuda13.3`, using
`cuda-toolkit-13-3` under `/usr/local/cuda-13.3`. It uses the SDK directly,
without the CUDA 12.9 header workaround. The GPU targets start at Turing and
include Blackwell sm_120a and sm_121a images; CUDA 12.x packages retain support
for Maxwell, Pascal and Volta.

The plugin is installed under `backends/cuda13.3`, resolves runtime libraries
from the versioned SDK, and uses the `tllama-server-cuda` alternatives group
with priority 133. Runtime and cuBLAS dependencies are explicit; local driver
metadata requires `libcuda1 (>= 580)`.

## SYCL package

```sh
dpkg-checkbuilddeps -Ppkg.tllama-server.sycl-only
debuild -Ppkg.tllama-server.sycl-only -j"$(nproc)"
```

This profile builds only the SYCL package in `build-debian-sycl`. It selects
oneAPI icx/icpx, oneMKL, oneDNN and TBB explicitly under `/opt/intel/oneapi`,
without requiring an interactive `setvars.sh`. The native GCC installation
reported by the default `g++` supplies the C++ runtime and headers, avoiding
accidental selection of installed cross toolchains. Debian hardening flags are
preserved alongside this GCC selection; GCC-specific LTO flags are disabled
for the IntelLLVM profile.

The Intel target enables FP16, SYCL graphs, host-memory fallback, Level Zero
and oneDNN. The device architecture is left unset to produce portable SYCL
device code rather than an image restricted to the build host GPU.

The module is installed under `backends/sycl`; `tllama-server-sycl` alternatives
supplies the loader link at `/usr/lib/tllama/server/libggml-sycl.so`. Its runtime
paths include the compiler, oneMKL, oneDNN and TBB library directories. oneAPI
runtime package dependencies are explicit, while shlibdeps collects standard
Debian dependencies. Building does not require an Intel GPU.
