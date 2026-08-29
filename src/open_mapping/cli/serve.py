"""Optional HTTP sidecar command."""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path

from open_mapping.cli.common import CliInputError
from open_mapping.mapper import Mapper


def _loopback(host: str) -> bool:
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def serve_command(
    bundle: Path,
    *,
    host: str,
    port: int,
    allow_remote: bool,
    api_key_env: str | None,
) -> int:
    loopback = _loopback(host)
    if not loopback and not allow_remote:
        raise CliInputError("non-loopback hosts require --allow-remote")
    if not loopback and api_key_env is None:
        raise CliInputError("non-loopback hosts require --api-key-env")
    api_key = None
    if api_key_env is not None:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise CliInputError(f"required API key environment variable {api_key_env} is not set")
    try:
        import uvicorn

        from open_mapping.server.app import create_app
    except ImportError as error:
        raise CliInputError(
            "server dependencies are not installed; install open-mapping[server]"
        ) from error
    mapper = Mapper.load(bundle)
    uvicorn.run(
        create_app(mapper, api_key=api_key),
        host=host,
        port=port,
        access_log=False,
    )
    return 0


__all__ = ["serve_command"]
