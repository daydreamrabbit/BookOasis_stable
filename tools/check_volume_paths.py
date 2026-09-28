#!/usr/bin/env python3
"""Fail closed when a configured bind-mount path is absent or disconnected."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys


def check_path(path: str) -> None:
    """Touch a directory or regular file without changing its contents."""
    info = os.stat(path)
    if stat.S_ISDIR(info.st_mode):
        with os.scandir(path) as entries:
            next(entries, None)
    elif stat.S_ISREG(info.st_mode):
        with open(path, "rb") as mounted_file:
            mounted_file.read(1)
    else:
        raise OSError(f"unsupported bind source type: {stat.filemode(info.st_mode)}")


def compose_bind_paths() -> list[tuple[str, str, str]]:
    """Return (service, target, source) tuples from the resolved Compose model."""
    try:
        result = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        config = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise RuntimeError("could not resolve docker-compose.yml") from exc

    paths = []
    for service_name, service in config.get("services", {}).items():
        for volume in service.get("volumes", []):
            if volume.get("type") == "bind":
                paths.append((service_name, volume.get("target", "?"), volume["source"]))
    return paths


def main() -> int:
    if sys.argv[1:] == ["--compose-config"]:
        try:
            checks = compose_bind_paths()
        except RuntimeError as exc:
            print(f"[volume-check] ERROR: {exc}", file=sys.stderr)
            return 1
    else:
        checks = [("container", path, path) for path in sys.argv[1:]]

    if not checks:
        print("[volume-check] ERROR: no bind paths were provided", file=sys.stderr)
        return 2

    failures = []
    for service, target, source in checks:
        try:
            check_path(source)
        except (OSError, ValueError) as exc:
            failures.append((service, target, source, exc))

    if failures:
        for service, target, source, error in failures:
            print(
                f"[volume-check] ERROR: service={service} target={target} "
                f"source={source}: {error}",
                file=sys.stderr,
            )
        return 1

    print(f"[volume-check] OK: {len(checks)} bind paths are accessible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
