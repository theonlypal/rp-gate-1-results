# RP-GATE-1 executable contract

PREREG.md is the full scientific preregistration. protocol.json contains exact Unicode messages, target identities, model snapshots, settings, classifier rules and thresholds. schedule.json contains all 160 ordered slots. build_protocol.py materializes both offline, without networking.

## Preparation

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 run.py --freeze
git add -A
git commit -m "freeze protocol before inference"
```

Record that commit in FREEZE_COMMIT.txt, commit the pointer, tag and publish the preregistration. Publish and verify its Zenodo DOI before inference. Never regenerate or edit a freeze after observation.

## Run

Clone the preregistration repository into a new results directory, preserving Git history. Supply OPENAI_API_KEY and the verified funded OPENAI_ORGANIZATION in process environment only; GitHub authentication is read from the existing gh login. Check account funding privately first. Do not expose keys in command arguments or shell history. The organization header routes billing and is excluded from public evidence.

```sh
python3 run.py --prereg-doi ACTUAL_PUBLISHED_DOI --funding-verified
python3 verify.py
python3 analyze.py
```

The funding flag is a human/operator assertion based on an actual account check, not an automatic credit purchase or a substitute for checking. The runner refuses existing events.jsonl and has no resume/retry path. A partial execution must remain partial.

## Seal and offline verification

Build SHA256SUMS.txt over all tracked and untracked non-ignored files except itself. Then:

```sh
python3 verify.py --manifest
python3 -m unittest discover -s tests -v
```

Commit, tag and publish the results; verify again from a fresh clone at that tag. Verification uses Python standard library and Git only. Token estimation and running use tiktoken; no paid inference is involved in verification or tests. The ZIP excludes .git, so use a GitHub clone for ancestry checks. All source and data files are also present in the tagged ZIP.

Record claims separately: model proposal selection; successful empty normal termination; application authorization; observed GitHub write/readback. An external denial is not a model Void. A signed/hash-bound local record is not hardware attestation.
