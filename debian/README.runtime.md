# TLlama server

`tllama-server` is the native inference server used by TLlama. It runs GGUF
models and provides an HTTP API compatible with OpenAI clients. TLlama can
manage server processes; the executable can also be started directly.

## Features

- Text generation and chat through the OpenAI-compatible API.
- Multimodal models with a matching projector file.
- CPU inference with automatic selection of the supported CPU instruction set
  and an OpenBLAS backend.
- Optional Vulkan, ROCm/HIP and CUDA GPU backends.
- The HIP backend distinguishes `gfx1250` and selects compatible kernels for
  that architecture, extending the pinned upstream implementation.

## Packages

Install `tllama-server` for the core runtime and CPU/OpenBLAS support.
GPU support is provided by optional packages:

- `tllama-server-backend-vulkan` uses the system Vulkan drivers.
- `tllama-server-backend-rocm10.1` uses AMD ROCm 10.1. The required ROCm runtime
  and BLAS packages are installed through package dependencies.
- `tllama-server-backend-cuda12.4` supports NVIDIA Maxwell through Hopper GPUs,
  including Pascal Tesla P100. A compatible NVIDIA driver is required; CUDA
  runtime libraries are installed through package dependencies.
- `tllama-server-backend-cuda12.9` additionally supports Blackwell GPUs.
- `tllama-server-backend-cuda13.3` supports Turing through Blackwell GPUs and
  requires an NVIDIA 580 or newer driver. For Maxwell, Pascal (including P100)
  and Volta, use a CUDA 12.x backend.

CUDA plugins can be installed together. Automatic selection prefers the highest
version; to select a suitable backend for an older GPU, run
`sudo update-alternatives --config tllama-server-cuda`.

GPU backends require the matching core and CPU package versions. The ROCm 10.1
package does not contain kernels for legacy Vega `gfx900`, `gfx906` or `gfx90c`.
For those devices, Vulkan is an alternative when the installed driver supports
compute. ROCm device discovery alone does not establish kernel compatibility.

## Run a model

For a local CPU server:

```sh
/usr/lib/tllama/server/tllama-server \
    --model /path/to/model.gguf --alias local \
    --host 127.0.0.1 --port 8080 --n-gpu-layers 0
```

List available acceleration devices:

```sh
/usr/lib/tllama/server/tllama-server --list-devices
```

To use a listed GPU, replace `--n-gpu-layers 0` with, for example,
`--device Vulkan0 --n-gpu-layers 99` or
`--device ROCm0 --n-gpu-layers 99` or
`--device CUDA0 --n-gpu-layers 99`. The layer count must suit the model and
available GPU memory. CPU devices are omitted from `--list-devices`.

For a supported multimodal model, also specify its matching projector with
`--mmproj /path/to/projector.gguf`.

## Call the API

With the example server running:

```sh
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{"model":"local","messages":[{"role":"user","content":"Hello!"}],"max_tokens":64}'
```

Use `http://127.0.0.1:8080/v1` as the base URL in an OpenAI-compatible client.
Available model features depend on the GGUF model and its chat template.

For all server options:

```sh
/usr/lib/tllama/server/tllama-server --help
```
