# RP-GATE-1

Prerequisite-conditioned noncontinuation and execution-time revocation.

160 preregistered Chat Completions requests across `gpt-5.4-2026-03-05` and `gpt-5.2-2025-12-11`. Two system prompts differ only in the Arabic prerequisite. A separate application gate controls real writes to a disposable GitHub issue.

[Preregistration](PREREG.md) · [Protocol](PROTOCOL.md) · [Exact configuration](protocol.json) · [Schedule](schedule.json)

No inference results are included in this preregistration. A public Zenodo preregistration DOI is required before execution.

```sh
python3 -m unittest discover -s tests -v
python3 verify.py
```

Before execution the verifier must fail on missing events.jsonl. Tests use synthetic fixtures only, not experimental observations.

Author: Rayan Pal. Code and research records: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/.
