# Contributing

Commons is meant to be useful to doctoral candidates in any field. Contributions that make it more useful,
more honest or easier to set up are welcome.

## Good first contributions

- A feed adapter for a source your field relies on (PubMed E-utilities, bioRxiv, SSRN, a national statistics API).
- A provider preset for a runtime or institutional service you have tested.
- A worked example in another discipline under `examples/` (fictional thesis, real public feeds).
- An analysis module that other projects in your field could reuse.
- Translations of the portal and the docs.

## Rules that do not bend

Pull requests are reviewed against the method in `docs/method.md`. In particular, a change will not be merged if it:

- lets model output count as evidence, or lets a figure be drawn from model-typed numbers;
- weakens the mechanical quote check or the tier policy;
- sends RESTRICTED material anywhere but a local or approved institutional model;
- adds telemetry, analytics or any network call the user did not configure.

## Development

```bash
git clone https://github.com/phd-commons/commons
cd phd-commons
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Tests use the deterministic fake provider and mock HTTP transports, so they need no models and no network.
Keep it that way: a test that needs a live model belongs behind an environment variable and is skipped by default.

Write plainly. Code comments and docs use plain sentences and say what something does and why.
