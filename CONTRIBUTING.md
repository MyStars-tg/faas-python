# Contributing

Thanks for your interest in `mystars-faas`, the MyStars FaaS Python SDK!

## This repo is a mirror

`github.com/mystars-tg/faas-python` is an **automatic mirror** of the official MyStars FaaS SDK. The
`main` branch here is **force-pushed** whenever SDK changes land upstream, so **pull requests
opened against this mirror cannot be merged** — they would be overwritten on the next sync.

**Please contribute via issues instead:**

- 🐛 **Found a bug?** Open an issue with a minimal repro (SDK version, Python version, the call you
  made, what happened vs. what you expected). See the issue templates.
- 💡 **Want a feature or a change?** Open an issue describing the use case. If you have a patch, paste
  the diff or a code sketch — the maintainers will apply it upstream and it flows back here,
  with credit.

## Running the SDK locally

```bash
git clone https://github.com/mystars-tg/faas-python
cd faas-python
pip install -e ".[dev]"
ruff check mystars_faas tests   # lint
mypy mystars_faas               # strict type-check
pytest -q                       # run the suite
```

The cross-language golden vectors in [`contract/`](contract/) are asserted by the tests, so behaviour
stays provably identical between the Python and TypeScript SDKs and provably matches the server.

## Conventions

- Python ≥ 3.9, `ruff` + `mypy --strict`, only runtime dependency is `httpx`.
- **Money is never a float** — amounts stay `Decimal` end to end.
- **Non-custodial** — the payment builders hold no keys and sign nothing; you sign with your own
  wallet or TON Connect.

## Security

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md). Do **not** open a public
issue for a security report.

## License

By contributing you agree your contribution is licensed under the [MIT License](LICENSE).
