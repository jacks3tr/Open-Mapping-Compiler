# HTTP sidecar

Create and review an AI-assisted or offline mapping, then serve its verified `.omc` bundle. The running sidecar does not call a model or either business system.

## Complete local example

From a checkout, install the optional dependencies and export the bundled example:

```text
python -m pip install ".[server]"
open-mapping demo --out-dir example
open-mapping serve example/mapping.omc
```

The default bind is loopback on port 8080. In another terminal:

```sh
curl --fail --json '{"input":{"customer_id":"C-100","name":"Ada"}}' http://127.0.0.1:8080/transform
```

Expected response:

```json
{"output":{"customerId":"C-100","displayName":"Ada"}}
```

Use `curl.exe` in PowerShell where `curl` is an alias. Replacing the identifier with `3` returns HTTP `422` with a `SOURCE_SCHEMA_VALIDATION` issue. The [TypeScript client](../examples/typescript/README.md) provides native-fetch methods without additional runtime dependencies.

## Request contracts

The sidecar loads and verifies one bundle at startup. Request bodies are limited to 10 MiB and batches to 1,000 records.

| Endpoint | Body | Successful response |
| --- | --- | --- |
| `GET /health` | None | Health status |
| `GET /metadata` | None | Mapping and verification metadata |
| `POST /validate` | `{"input": ...}` | `{"valid": true/false, "issues": [...]}` |
| `POST /transform` | `{"input": ...}` | `{"output": ...}` |
| `POST /transform-batch` | `{"inputs": [...]}` | `{"outputs": [...]}`; fail-fast by default |
| `POST /transform-batch` | `{"inputs": [...], "on_error": "collect"}` | `{"results": [{"index": 0, "success": true, "output": ..., "issues": []}, ...]}` |

Collected results preserve every zero-based input position. Per-record failures are represented inside the HTTP `200` batch response; inspect `success` rather than treating the transport status as proof every record passed. Invalid requests and fail-fast mapping failures still use error responses.

Source validation reuses the prepared validator. Transformation work runs outside the event loop with a four-operation concurrency limit, keeping health checks responsive. Thread offloading is not a claim of greater CPU throughput. Bound requests at your ingress and scale processes according to measured workload.

## Remote access

Set `OPEN_MAPPING_SERVER_KEY` to an application-generated secret in the process environment, then explicitly permit a remote bind:

```text
open-mapping serve example/mapping.omc --host 0.0.0.0 --allow-remote --api-key-env OPEN_MAPPING_SERVER_KEY
```

Send `Authorization: Bearer <value>` on every request, including health checks. Use TLS at a reverse proxy outside the local machine. The server does not enable CORS or log the token. The host application owns tenant isolation, request admission, token rotation, and retries.

## Versioned container

Release automation builds, tests, and publishes images under `ghcr.io/jacks3tr/open-mapping-compiler:<version>` and a commit-SHA tag. Use a version that has actually passed publication and anonymous pull verification; see [release setup](releasing.md). The workflow targets Linux amd64 and does not imply other architectures were tested.

Set the bearer secret in your environment, replace the bundle path and verified image version, then run:

```sh
docker run --rm -p 127.0.0.1:8080:8080 -e OPEN_MAPPING_SERVER_KEY -v /absolute/path/mapping.omc:/data/mapping.omc:ro ghcr.io/jacks3tr/open-mapping-compiler:<version>
```

Binding the host port to loopback avoids accidentally exposing the container to the network. Mount the bundle read-only. The image runs as user 10001, contains no bundle or credentials, and installs locked runtime dependencies without retaining the build toolchain.

Before an image is published, build the same Dockerfile locally with `docker build -t open-mapping .` and substitute `open-mapping` for the registry image above.
