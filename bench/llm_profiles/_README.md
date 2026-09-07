# LLM profiles

One TOML per model. `setup_bench.py --profile <name>` copies the `[llm]` table
into the bench project's `lens.toml` as its single `[[llm]]` entry (id `bench`).

Model choice and pricing are tracked in the issue that owns them, not here —
prices move weekly and a table in this file is wrong within days.

## A profile describes an endpoint, not a policy

It carries `base_url`, `model`, the key env var, timeouts, temperature, and
provider routing.

It does **not** carry thinking mode. `reasoning` / `reasoning_effort` are
per-operator decisions with three better homes already — `[operator.<name>]`,
`[params]`, and front-matter pins — and fixing one answer in the profile would
force it on every operator that uses the model.

`extra_headers` / `extra_payload` are the exception: they exist only on the
`[[llm]]` row and cannot be overridden per operator, which is why provider
pinning belongs here.

## Two things that will bite a scored run

**Pin the provider for open-weight models.** The same slug is served by many
vendors at different quantizations, and routing changes between runs — one smoke
test spread four models across four hosts. Unpinned, a comparison measures
vendors, not models:

```toml
[llm.extra_payload]
provider = { order = ["<vendor>"], allow_fallbacks = false }
```

**`:batch` variants are half price and asynchronous.** They do not stream and
are unusable through the Lens LLM client, so a batch price is never the price
you will pay for interactive generation.
