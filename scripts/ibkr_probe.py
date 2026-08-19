"""Ask a live IB Gateway what it actually returns - W1.1, read-only.

    .\\.venv\\Scripts\\python.exe scripts/ibkr_probe.py --label "run 1"

**Not to be confused with `scripts/broker_capabilities.py`**, which inspects
our own adapter classes with `hasattr`, connects to nothing, and therefore
prints the same table whether or not an IBKR account exists. That script
answers "what does OUR adapter implement". This one answers the half only a
Gateway can: what does IBKR return, in what shape, and does it raise.

Reads only. It calls no order-placing method and `tests/data/broker/
test_ib_probe.py::test_the_probe_never_writes` is what keeps that true. The
connection itself is opened with ib_async's `readonly=True`, which is an
IBKR API-level read-only session rather than a promise made in Python.

Two guards before anything is asked: a live PORT is refused in paper mode
(W1.4's rule, which the probe does not inherit because it connects on its own
rather than through `IBAdapter`), and a live ACCOUNT NUMBER is refused after
connecting - paper accounts are prefixed `DU`, and the port being right does
not prove the Gateway is logged into the paper session.

**The permId question needs two runs.** Task 3 records `permId` as the order
identity because `orderId` is per-session, and recorded that permId surviving
a Gateway restart was assumed rather than measured. Run this, restart the
Gateway, run it again with a different `--label`, and compare the permIds in
the two reports.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.config import Settings  # noqa: E402
from qat.data.broker.ib_probe import (  # noqa: E402
    check_paper_account,
    connection_target,
    observed_perm_ids,
    probe,
    render,
)

# The MACHINE-written half. The report a human writes and reasons in lives at
# 2026-08-19-ibkr-capability-measurement.md and cites this; keeping them apart
# is what stops a re-run silently erasing the interpretation.
DEFAULT_OUT = Path("docs/superpowers/specs/2026-08-19-ibkr-capability-measurement-raw.md")


def _settings() -> Settings:
    """The operator's real IBKR host/port, with `data_dir` pointed elsewhere.

    `Settings(_env_file=None).data_dir` is the LIVE data directory and
    `conftest` only protects tests. This script writes nothing there, and
    passing its own directory is what keeps that structural rather than
    incidental.
    """
    return Settings(data_dir=tempfile.mkdtemp(prefix="qat-probe-"))


async def _run(out: Path, label: str) -> int:
    from ib_async import IB

    settings = _settings()
    host, port, client_id = connection_target(settings)

    ib = IB()
    print(f"connecting read-only to {host}:{port} as clientId={client_id} ...")
    await ib.connectAsync(host, port, clientId=client_id, readonly=True, timeout=15)
    try:
        accounts = ib.managedAccounts()
        check_paper_account(accounts)
        print(f"connected: {accounts}")

        observations = await probe(ib)
    finally:
        ib.disconnect()

    report = render(observations, account=", ".join(accounts))
    header = f"<!-- {label} -->\n\n" if label else ""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + report, encoding="utf-8")

    for observation in observations:
        print(f"  {observation.call:28} {observation.outcome}")
    print(f"\npermIds observed: {observed_perm_ids(observations) or 'none'}")
    print(f"report written to {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--label", default="", help='e.g. "run 1, before Gateway restart"')
    args = parser.parse_args()
    return asyncio.run(_run(args.out, args.label))


if __name__ == "__main__":
    raise SystemExit(main())
