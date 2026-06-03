"""Parse Git remote URLs for SSH host key setup (Fly deploy, etc.)."""

from __future__ import annotations

import re
from urllib.parse import urlparse


def parse_git_ssh_remote(url: str) -> tuple[str, int]:
    """Return ``(hostname, port)`` for SSH ``git clone``/``fetch`` of this remote.

    Supports SCP-like ``git@host:path`` and ``ssh://`` URLs. Rejects ``https://``,
    ``http://``, and other schemes — Fly deploy uses an SSH deploy key, not HTTPS
    credentials.

    Raises:
        ValueError: If the URL is not a supported SSH-oriented Git remote.
    """
    u = url.strip()
    if not u:
        raise ValueError("remote URL is empty")

    lowered = u.lower()
    if lowered.startswith(("https://", "http://")):
        raise ValueError(
            "origin uses an HTTPS URL; Fly deploy needs an SSH URL "
            "(for example git@github.com:org/repo.git) so the deploy key can authenticate"
        )

    if lowered.startswith("ssh://"):
        return _from_ssh_scheme(u)

    if "://" in u:
        raise ValueError(
            "unsupported remote URL scheme for Fly deploy; use an SSH URL "
            "(for example git@github.com:org/repo.git)"
        )

    return _from_scp_like(u)


def _from_scp_like(url: str) -> tuple[str, int]:
    m = re.match(r"^[^@]+@(\[[^\]]+\]|[^:]+):", url)
    if not m:
        raise ValueError(
            "could not parse SSH host from remote URL; expected git@host:path "
            "or ssh://git@host/..."
        )
    host = m.group(1)
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host, 22


def _from_ssh_scheme(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "ssh":
        raise ValueError("internal: expected ssh:// URL")

    netloc = parsed.netloc
    if not netloc:
        raise ValueError("ssh:// remote URL has no host")

    if "@" in netloc:
        _, rest = netloc.rsplit("@", 1)
    else:
        rest = netloc

    if rest.startswith("["):
        end = rest.find("]")
        if end == -1:
            raise ValueError("malformed IPv6 host in ssh:// remote URL")
        host = rest[1:end]
        tail = rest[end + 1 :]
        if tail.startswith(":") and tail[1:].isdigit():
            return host, int(tail[1:])
        return host, 22

    if ":" in rest:
        host, port_s = rest.rsplit(":", 1)
        if port_s.isdigit():
            return host, int(port_s)
        return rest, 22

    return rest, 22
