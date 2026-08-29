# HTTP sidecar

Install the optional server dependencies:

```text
pip install "open-mapping[server]"
```

Serve one bundle on loopback:

```text
open-mapping serve mapping.omc
```

The sidecar provides `/health`, `/metadata`, `/validate`, `/transform`, and `/transform-batch`. It loads and verifies the bundle once at startup. Request bodies are limited to 10 MiB and batches are limited to 1,000 records.

A non-loopback bind needs both an explicit remote flag and a bearer token environment variable:

```text
open-mapping serve mapping.omc --host 0.0.0.0 --allow-remote --api-key-env OPEN_MAPPING_SERVER_KEY
```

Send the token as `Authorization: Bearer <value>`. The server does not enable CORS or log the token.

## Run the container

Build the local image, mount a verified bundle, and supply the bearer token at runtime:

```text
docker build -t open-mapping .
docker run --rm -p 8080:8080 -e OPEN_MAPPING_SERVER_KEY -v /absolute/path/mapping.omc:/data/mapping.omc:ro open-mapping
```

The image runs as an unprivileged user. It does not contain a bundle or credentials. Replace the host path with an absolute path to your `.omc` file.
