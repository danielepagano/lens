#!/usr/bin/env python3
"""Build a pinned ``[[llm]]`` row for a bench arm, and refuse the known traps.

Both halves of the re-rating loop (issue #140) say "wire the shortlist as named
``[[llm]]`` rows" and then spend a paragraph on how to get that wrong. This is
that paragraph, executable. It is the one step that recurs *every* time the
field moves, and rarely is exactly when you have forgotten which mistakes cost
money last time.

What it refuses or flags, all of it paid for already:

* **Pinning by provider name instead of tag.** OpenAI lists ``openai/flex``,
  ``openai`` and ``openai/fast`` on one dated snapshot at 1x, 2x and 4x the
  price. ``provider = { order = ["OpenAI"] }`` leaves the router free among
  them, and flex-against-fast is a *latency* difference — which is one of the
  things a ranking pass measures. So the row is pinned to a tag, and a provider
  serving several tags is called out by name.
* **Quantization as part of the price.** A standout bargain is routinely an fp4
  endpoint quoted against a first-party fp8 list price. The listing shows the
  quant next to the money so "cheapest" cannot be read without it.
* **``:batch`` variants.** Asynchronous, non-streaming, unusable through the
  Lens client, and priced to look like a discount. Refused outright.
* **``~``-prefixed floating aliases.** A measurement cannot be reproduced
  against an id that moves. Refused outright.
* **Endpoints that drop ``temperature``.** ``gpt-5.6-luna`` accepts none at all,
  and Lens will happily record in the trace the temperature it *sent* rather
  than one that was honoured. The row omits the field and says so.

It also owns the **canonical arm configuration**, which is the other reason it
exists. A comparison against an earlier run is void if the arms were not
configured the same way, and until this file that configuration lived only
inside gitignored banked traces — reconstructible today by grepping them, and
not reconstructible at all from a fresh clone. It is now one constant, and the
scenarios point here instead of restating it.

Usage::

    # What endpoints exist, what they cost, and at what quantization
    python bench/tools/llm_row.py deepseek/deepseek-v4.1-pro

    # The row itself, pinned to one tag
    python bench/tools/llm_row.py deepseek/deepseek-v4.1-pro --pin deepseek --id ds-pro

Paste the result into the bench project's ``lens.toml``. It is deliberately not
written there for you: a tool that edits a config it did not create is a worse
trade than a copy and paste.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

_API = "https://openrouter.ai/api/v1/models"

# The canonical bench arm. Every arm of every gate and ranking run uses these,
# and a run that deviates cannot be compared with an earlier one — which is the
# entire point of a loop whose answers have a shelf life. They match the first
# gate sweep and the first ranking sweep, so today's numbers stay a baseline.
#
# `temperature` is 0.6 rather than a profile's 0.9 because the `write` sweep
# preferred it, by a margin inside what n=2 can produce by chance. It is a bet
# held constant, not a result — but held constant is what matters here.
CANONICAL = {
    "temperature": 0.6,
    "reasoning": True,
    "reasoning_effort": "medium",
    "timeout_seconds": 300,
    "first_token_timeout_seconds": 90,
}


@dataclass(frozen=True)
class Endpoint:
    tag: str
    provider: str
    quantization: str
    prompt_usd: float
    completion_usd: float
    context: int
    params: frozenset[str]

    @property
    def takes_temperature(self) -> bool:
        return "temperature" in self.params

    @property
    def takes_effort(self) -> bool:
        return "reasoning_effort" in self.params


def refuse(model_id: str) -> str | None:
    """Why this id must not be measured against, or None if it is fine."""
    if model_id.startswith("~"):
        return (
            "a `~`-prefixed id is a floating alias — it points somewhere else "
            "next week, and a measurement cannot be reproduced against it"
        )
    if ":batch" in model_id:
        return (
            "`:batch` is asynchronous and does not stream, so the Lens client "
            "cannot use it at all. Its price is not an interactive price"
        )
    return None


def fetch(model_id: str) -> list[Endpoint]:
    url = f"{_API}/{model_id}/endpoints"
    headers: dict[str, str] = {}
    key = os.environ.get("OPEN_ROUTER_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=30
        ) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{model_id}: {exc.code} {exc.reason} — is the id spelled right?")
    except urllib.error.URLError as exc:
        raise SystemExit(f"could not reach OpenRouter: {exc.reason}")

    out: list[Endpoint] = []
    for e in payload.get("data", {}).get("endpoints", []):
        pricing = e.get("pricing", {})
        out.append(
            Endpoint(
                tag=str(e.get("tag") or ""),
                provider=str(e.get("provider_name") or "?"),
                quantization=str(e.get("quantization") or "unknown"),
                prompt_usd=float(pricing.get("prompt") or 0) * 1e6,
                completion_usd=float(pricing.get("completion") or 0) * 1e6,
                context=int(e.get("context_length") or 0),
                params=frozenset(e.get("supported_parameters") or []),
            )
        )
    return out


def hazards(endpoints: list[Endpoint]) -> list[str]:
    """Warnings a person must read before choosing a tag."""
    notes: list[str] = []

    # The luna trap: one provider, several tags, a 4x price spread between them,
    # and a provider-name pin that silently picks among them.
    by_provider: dict[str, list[Endpoint]] = {}
    for e in endpoints:
        by_provider.setdefault(e.provider, []).append(e)
    for provider, group in sorted(by_provider.items()):
        if len(group) > 1:
            tags = ", ".join(sorted(e.tag or "(no tag)" for e in group))
            spread = max(e.prompt_usd for e in group) / max(
                1e-9, min(e.prompt_usd for e in group)
            )
            # Only quote a spread that is one. Printing "up to 1x price spread"
            # reads as noise and teaches the reader to skip the whole section,
            # which is where the 4x case also lives.
            cost = (
                f"at up to a {spread:.1f}x price spread"
                if spread >= 1.2
                else "at the same price but different routes"
            )
            notes.append(
                f"{provider} serves {len(group)} endpoints ({tags}) {cost} — "
                "pin the TAG, not the provider name"
            )

    # Quantization as part of the price: the cheapest row being a lower quant
    # than some other row is the shape that makes a bargain a different model.
    priced = [e for e in endpoints if e.prompt_usd > 0]
    if priced:
        cheapest = min(priced, key=lambda e: e.prompt_usd)
        if cheapest.quantization in {"fp4", "nvfp4", "int4", "unknown"} and any(
            e.quantization == "fp8" for e in priced
        ):
            notes.append(
                f"cheapest endpoint ({cheapest.tag or cheapest.provider}) is "
                f"{cheapest.quantization} while fp8 is available — comparing it "
                "with an fp8 list price compares two different models"
            )

    if endpoints and not any(e.takes_effort for e in endpoints):
        notes.append(
            "no endpoint accepts reasoning_effort — an arm cannot be run at a "
            "stated effort on this model"
        )
    return notes


def render_row(llm_id: str, model_id: str, endpoint: Endpoint) -> str:
    """The ``[[llm]]`` row, at the canonical configuration, pinned to one tag."""
    lines = [
        f"# {model_id} via {endpoint.provider}, quant={endpoint.quantization}, "
        f"${endpoint.prompt_usd:.2f}/${endpoint.completion_usd:.2f} per 1M",
        "# Canonical bench arm (bench/tools/llm_row.py CANONICAL). Changing",
        "# temperature or reasoning here voids comparison with earlier runs.",
        "[[llm]]",
        f'id = "{llm_id}"',
        'base_url = "https://openrouter.ai/api/v1"',
        'api_key_env = "OPEN_ROUTER_API_KEY"',
        f'model = "{model_id}"',
    ]
    if endpoint.takes_temperature:
        lines.append(f"temperature = {CANONICAL['temperature']}")
    else:
        lines.append(
            "# temperature omitted: this endpoint does not accept it, and Lens"
        )
        lines.append(
            "# would record in the trace the value it sent, not one honoured."
        )
    lines += [
        f"reasoning = {str(CANONICAL['reasoning']).lower()}",
        f'reasoning_effort = "{CANONICAL["reasoning_effort"]}"',
        f"timeout_seconds = {CANONICAL['timeout_seconds']}",
        f"first_token_timeout_seconds = {CANONICAL['first_token_timeout_seconds']}",
        "",
        "# If a call fails with 'Reasoning is mandatory for this endpoint",
        "# and cannot be disabled', add this — it is row-only and only ever",
        "# raises the effort, so it cannot be lowered by an invocation:",
        '#   reasoning_floor = "low"',
        "",
        "[llm.extra_payload.provider]",
        f'order = ["{endpoint.tag}"]',
        "allow_fallbacks = false",
    ]
    return "\n".join(lines)


def _listing(model_id: str, endpoints: list[Endpoint]) -> None:
    print(f"\n=== {model_id} — {len(endpoints)} endpoint(s)")
    print(f"  {'tag':<26} {'provider':<16} {'quant':<8} {'in':>7} {'out':>7}  temp effort")
    for e in sorted(endpoints, key=lambda x: x.prompt_usd):
        print(
            f"  {(e.tag or '(none)'):<26} {e.provider:<16} {e.quantization:<8} "
            f"{e.prompt_usd:>7.2f} {e.completion_usd:>7.2f}  "
            f"{'yes' if e.takes_temperature else ' no':<4} "
            f"{'yes' if e.takes_effort else 'no'}"
        )
    notes = hazards(endpoints)
    if notes:
        print("\n  hazards:")
        for note in notes:
            print(f"    - {note}")
    print(
        "\n  Pick a tag and re-run with --pin <tag> --id <arm-id>. Prefer the"
        "\n  first-party endpoint at the highest quantization: it is the"
        "\n  reference the vendor's own list price describes."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("model", nargs="+", help="OpenRouter model id(s)")
    parser.add_argument("--pin", default=None, metavar="TAG", help="emit a row pinned to this tag")
    parser.add_argument("--id", default=None, help="the [[llm]] id for the emitted row")
    args = parser.parse_args(argv)

    if args.pin and len(args.model) != 1:
        parser.error("--pin takes exactly one model")
    if args.pin and not args.id:
        parser.error("--pin needs --id, the name the arm is referred to by")

    for model_id in args.model:
        why = refuse(model_id)
        if why:
            print(f"{model_id}: refused — {why}", file=sys.stderr)
            return 1

    if not args.pin:
        for model_id in args.model:
            _listing(model_id, fetch(model_id))
        return 0

    model_id = args.model[0]
    endpoints = fetch(model_id)
    match = [e for e in endpoints if e.tag == args.pin]
    if not match:
        tags = ", ".join(sorted(e.tag for e in endpoints if e.tag)) or "(none)"
        print(f"no endpoint tagged {args.pin!r}. Available: {tags}", file=sys.stderr)
        return 1
    print(render_row(args.id, model_id, match[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
