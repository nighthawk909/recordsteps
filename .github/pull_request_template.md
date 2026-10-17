## What and why

<!-- What changes for people using Record Steps, and why. Link the issue if there is one. -->

## How it was verified

- [ ] `python -m ruff check .`
- [ ] `python -m pytest -q` (CI also enforces 80% coverage)
- [ ] Capture changes: `QT_QPA_PLATFORM=windows python -m pytest -m desktop` passed (moves the real mouse; CI runs it too)
- [ ] Export changes: opened the resulting HTML / Word / PDF and looked at them
- [ ] Tried it in the running app (`python -m recordsteps`)

## Privacy check

- [ ] Nothing new is captured, stored or sent beyond what the README's privacy table promises
- [ ] No screenshots, recordings or logs with real people's data are committed (tests use the test window or synthetic images)

## Notes for reviewers

<!-- Anything risky, follow-ups, screenshots (no private info). -->
