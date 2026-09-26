# Genuine legacy execution receipts

These files were generated through the real OMS, bridge, and ledger at
`f7563759edbcb92c336cb07aa52dd91189571727` (before Task 2), using a fake broker.
The original producer ran separately with an isolated copy of the base source.
No crash JSON was hand-edited. The application UUID and order creation timestamp
are generated normally; the execution clock is fixed for reproducible replay.

- `settled`: four shares accepted under the application UUID, followed by the
  production late broker-ID resolution to `998877` and production persistence.
- `pending`: the same order reaches ten shares; the bridge durably accepts the
  six-share delta, while another critical subscriber raises `OSError`. The base
  OMS retains its four-share receipt and broker-keyed pending delivery.

`generate.py` preserves that producer as a reproducible fixture utility. Put
the base revision's `src` first on `PYTHONPATH` and pass a new, empty output
directory. It verifies the Git blob hashes of all three relevant production
modules before generating files, and refuses an existing destination. The
`settled` and `pending` subdirectories contain the fixture snapshots; `producer`
contains the full isolated production data. Run it in a separate process from
the current-version restart tests.
