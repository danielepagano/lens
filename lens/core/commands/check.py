"""Validate Lens project configuration and environment prerequisites."""

from __future__ import annotations

import os
import socket
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from lens.core.project import datasets_root, get_mount_point, get_selected_datasets
from lens.core.prompts import prompt_pack_file


# Same set as deploy (S3-compatible mounts; see lens.core.mount).
_MOUNT_S3_REQUIRED_ENV: tuple[str, ...] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ENDPOINT_URL",
    "AWS_DEFAULT_REGION",
)


@dataclass(frozen=True)
class CheckLine:
    """One human-readable check line (severity: ok | warn | error)."""

    severity: str
    topic: str
    detail: str


def _empty_check_lines() -> list[CheckLine]:
    return []


@dataclass
class ProjectCheckResult:
    lines: list[CheckLine] = field(default_factory=_empty_check_lines)

    @property
    def ok(self) -> bool:
        return not any(line.severity == "error" for line in self.lines)

    def add(self, severity: str, topic: str, detail: str) -> None:
        self.lines.append(CheckLine(severity=severity, topic=topic, detail=detail))


def _llm_label(index: int, entry: dict[str, Any]) -> str:
    raw_id = entry.get("id")
    if isinstance(raw_id, str) and raw_id.strip():
        return raw_id.strip()
    if index == 0:
        return "[default]"
    return f"[[llm]] #{index + 1}"


def _tcp_reachable(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        return False, f"address lookup failed: {e}"
    last_err = ""
    for res in infos:
        family, socktype, proto, _, sockaddr = res
        s: socket.socket | None = None
        try:
            s = socket.socket(family, socktype, proto)
            s.settimeout(timeout)
            s.connect(sockaddr)
            return True, ""
        except OSError as e:
            last_err = str(e)
        finally:
            if s is not None:
                s.close()
    return False, last_err or "connection failed"


def _check_llm_endpoint(base_url: str) -> tuple[bool, str]:
    parsed = urlparse(base_url.strip())
    if parsed.scheme not in ("http", "https"):
        return False, f"expected http(s) URL, got scheme {parsed.scheme!r}"
    host = parsed.hostname
    if not host:
        return False, "missing host in base_url"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    ok, err = _tcp_reachable(host, port)
    if ok:
        return True, f"reachable ({parsed.scheme}://{host}:{port})"
    return False, f"not reachable ({parsed.scheme}://{host}:{port}): {err}"


def run_project_check(project_root: Path, *, skip_network: bool = False) -> ProjectCheckResult:
    """Inspect ``lens.toml``, environment, and paths. Network checks unless *skip_network*."""
    result = ProjectCheckResult()
    lens_toml = project_root / "lens.toml"
    if not lens_toml.exists():
        result.add("error", "lens.toml", "not found")
        return result

    with lens_toml.open("rb") as f:
        config: dict[str, Any] = tomllib.load(f)

    raw_llm_list = config.get("llm", [])
    llm_list: list[Any] = cast(list[Any], raw_llm_list) if isinstance(raw_llm_list, list) else []
    if not llm_list:
        result.add("error", "llm", "no [[llm]] entries in lens.toml")
    else:
        for i, raw_entry in enumerate(llm_list):
            if not isinstance(raw_entry, dict):
                result.add("error", "llm", f"entry #{i + 1} is not a table")
                continue
            entry = cast(dict[str, Any], raw_entry)
            label = _llm_label(i, entry)
            base_url = entry.get("base_url", "")
            if not isinstance(base_url, str) or not base_url.strip():
                result.add("error", f"llm {label}", "missing base_url")
                continue
            base_url = base_url.strip()

            if skip_network:
                result.add("ok", f"llm {label}", f"base_url {base_url!r} (network check skipped)")
            else:
                ok, detail = _check_llm_endpoint(base_url)
                result.add("ok" if ok else "error", f"llm {label} endpoint", detail)

            api_key_env = entry.get("api_key_env", "")
            if isinstance(api_key_env, str) and api_key_env.strip():
                name = api_key_env.strip()
                val = os.environ.get(name)
                if val:
                    result.add("ok", f"llm {label} api_key_env", f"{name} is set")
                else:
                    result.add("error", f"llm {label} api_key_env", f"{name} is not set or empty")

    raw_project = config.get("project", {})
    project: dict[str, Any] = cast(dict[str, Any], raw_project) if isinstance(raw_project, dict) else {}

    raw_mount = project.get("mount_point")
    if isinstance(raw_mount, str) and raw_mount.strip():
        mp = raw_mount.strip()
        if mp.startswith("s3://"):
            result.add("ok", "mount", f"S3 URI {mp!r}")
            missing = [v for v in _MOUNT_S3_REQUIRED_ENV if not os.environ.get(v)]
            if missing:
                result.add(
                    "error",
                    "mount S3 env",
                    "not set or empty: " + ", ".join(missing),
                )
            else:
                result.add("ok", "mount S3 env", "AWS variables present")
        else:
            resolved = get_mount_point(project_root)
            if resolved is None:
                result.add("error", "mount", f"could not resolve local mount_point {mp!r}")
            elif resolved.is_dir():
                result.add("ok", "mount path", str(resolved))
            else:
                result.add(
                    "error",
                    "mount path",
                    f"{resolved} is not an existing directory",
                )
    else:
        result.add("ok", "mount", "not configured")

    pack = project.get("prompt_pack")
    if isinstance(pack, str) and pack.strip():
        p = pack.strip()
        pack_path = prompt_pack_file(p)
        if pack_path.is_file():
            result.add("ok", "prompt_pack", f"{p!r} -> {pack_path}")
        else:
            result.add("warn", "prompt_pack", f"{p!r} -> {pack_path} (file missing)")

    ds_names = get_selected_datasets(project_root)
    ds_root = datasets_root()
    for name in ds_names:
        p = ds_root / name
        if p.is_dir():
            result.add("ok", f"dataset {name}", str(p))
        else:
            result.add(
                "warn",
                f"dataset {name}",
                f"no bundled dataset directory at {p}",
            )

    narrative = project.get("narrative")
    if isinstance(narrative, str) and narrative.strip():
        slug = narrative.strip()
        nd = project_root / "narrative" / slug
        if nd.is_dir():
            result.add("ok", "narrative", f"{slug!r} -> {nd}")
        else:
            result.add(
                "warn",
                "narrative",
                f"{slug!r}: {nd} is not an existing directory (run lens use?)",
            )

    return result
