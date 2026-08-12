"""What each broker adapter implements, and what its gaps cost - derived now.

    .\\.venv\\Scripts\\python.exe scripts/broker_capabilities.py

Reporting only. Instantiates nothing, connects to nothing, and reads no
configuration - it inspects classes, so it is safe to run at any time.

This is the checklist the IBKR spike (W1.0 -> W1.1) measures against: every
name in the "not implemented" list is a question to put to a live Gateway
before the ASX cost can be estimated.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qat.data.broker.capabilities import (  # noqa: E402
    CORE,
    KNOWN_ADAPTERS,
    OPTIONAL,
    inspect_adapter,
    protocol_methods,
    unclassified,
)


def main() -> int:
    methods = sorted(protocol_methods())
    adapters = KNOWN_ADAPTERS()

    print("BrokerAdapter")
    print(f"  methods         {len(methods)}  ({len(CORE)} core, {len(OPTIONAL)} optional)")
    stray = sorted(unclassified())
    print(f"  unclassified    {len(stray)}{'  ' + ', '.join(stray) if stray else ''}")
    print()

    width = max(len(name) for name in methods) + 9
    header = "".join(f"{name:<10}" for name in adapters)
    print(f"  {'method':<{width}}{header}")
    for method in methods:
        kind = "core" if method in CORE else "opt"
        row = ""
        for adapter in adapters.values():
            row += f"{'yes' if hasattr(adapter, method) else 'NO':<10}"
        print(f"  {method + ' (' + kind + ')':<{width}}{row}")
    print()

    for key, adapter in adapters.items():
        caps = inspect_adapter(adapter)
        if caps.can_trade and not caps.missing_optional:
            print(f"{caps.adapter} ({key}) - implements the whole protocol")
            continue
        print(f"{caps.adapter} ({key})")
        if caps.missing_core:
            print(f"  CANNOT TRADE - missing core: {', '.join(sorted(caps.missing_core))}")
        for name in sorted(caps.missing_optional):
            print(f"  no {name}:")
            print(f"    {OPTIONAL[name]}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
