# Contributing

Retrogaze is open source. Bug reports, console-accuracy fixes, and docs improvements are welcome.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r src/requirements-lock.txt
pip install -r src/requirements-dev.txt
export RETROGAZE_MOCK=1   # development only: treats every request as a full-access user
cd src && python -m pytest tests/ -q
```

For real generation you need a [fal.ai](https://fal.ai) key in `FAL_KEY`.

## Rules of thumb

- Keep changes small and focused.
- Match existing style in the file you touch.
- Add or update tests next to the behavior you change.
- Do not commit `.env` files or API keys.
- `RETROGAZE_MOCK=1` is for local development and tests only. Never enable it on a public host.

## Pull requests

Say what you changed and how you checked it (which tests, which CLI/manual step).
