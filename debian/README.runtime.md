# TLlama server

`tllama-server` is the native inference server used by TLlama. It runs GGUF
models and provides an HTTP API compatible with OpenAI clients. TLlama can
manage server processes; the executable can also be started directly.

## Features

- Text generation and chat through the OpenAI-compatible API.
- Multimodal models with a matching projector file.
- CPU inference with automatic selection of the supported CPU instruction set
  and an OpenBLAS backend.
- Optional Vulkan, ROCm/HIP, CUDA and Intel SYCL GPU backends.
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

- `tllama-server-backend-sycl` supports Intel GPUs through oneAPI SYCL and
  Level Zero, with FP16 kernels, oneMKL and oneDNN. A compatible Intel compute
  driver is required; oneAPI runtime libraries are package dependencies.

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
    --host 127.0.0.1 --port 8080 \
    --device none --n-gpu-layers 0 --no-op-offload
```

List available acceleration devices:

```sh
/usr/lib/tllama/server/tllama-server --list-devices
```

To use a listed GPU, replace the CPU options
`--device none --n-gpu-layers 0 --no-op-offload` with, for example,
`--device Vulkan0 --n-gpu-layers 99` or
`--device ROCm0 --n-gpu-layers 99` or
`--device CUDA0 --n-gpu-layers 99`. For SYCL, use the device name reported
by `--list-devices`. The layer count must suit the model and
available GPU memory. CPU devices are omitted from `--list-devices`.

For example, start a Vulkan server with one request slot and a 2048-token
context:

```sh
/usr/lib/tllama/server/tllama-server \
    --model /path/to/model.gguf --alias local \
    --host 127.0.0.1 --port 8080 \
    --device Vulkan0 --n-gpu-layers 99 --ctx-size 2048 --parallel 1
```

Explicit device selection controls which GPU is used for inference. Installed
plugins may still print initialization messages for other backends.
Setting `--n-gpu-layers 0` alone does not disable offloading other operations;
use all three CPU options above for CPU inference.

For a supported multimodal model, also specify its matching projector with
`--mmproj /path/to/projector.gguf`.

## Call the API

With the example server running:

```sh
curl --max-time 10 --fail-with-body http://127.0.0.1:8080/health
curl --max-time 120 --fail-with-body http://127.0.0.1:8080/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{"model":"local","messages":[{"role":"user","content":"Hello!"}],"reasoning_effort":"none","max_tokens":128,"stream":false}'
```

Use `http://127.0.0.1:8080/v1` as the base URL in an OpenAI-compatible client.
Available model features depend on the GGUF model and its chat template.
During model loading, `/health` returns HTTP 503; wait for `{"status":"ok"}`
before sending the test request. The example disables reasoning when supported
by the model's template. To enable reasoning, omit `reasoning_effort` and allow
enough output tokens for both reasoning and the final answer. A response with
`finish_reason: "length"` may contain only `reasoning_content` if the token
limit is reached before the final answer.

For all server options:

```sh
/usr/lib/tllama/server/tllama-server --help
```
