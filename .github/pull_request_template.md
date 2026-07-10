# Summary

Describe the change and the problem it solves.

## Safety Impact

- Services affected:
- Files read:
- Files modified:
- External commands used:
- Repair level changed, if any:
- Rollback or verifier impact:

## Tests

List the exact commands you ran.

```bash
python -m compileall -q backup cli core repair services utils validators install.py main.py
python -m pytest
python -m ruff format --check .
python -m ruff check .
python -m mypy
```

## Checklist

- [ ] I did not test against real `/etc`, `/opt`, `/var/lib/lixet`, or `/usr/local/bin` paths.
- [ ] I added or updated regression tests for changed behavior.
- [ ] I kept uncertain findings report-only.
- [ ] I updated documentation only for behavior that exists in code.
- [ ] I removed secrets and private data from examples, logs, and fixtures.
