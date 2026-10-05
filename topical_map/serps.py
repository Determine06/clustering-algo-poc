"""Placeholder for deterministic SERP collection.

Intended update behavior:

* Fetch only keywords that do not already have a stored SERP result.
* Save successful results to ``data/serps.json``.
* Leave failed keywords without a successful result so they remain eligible
  for the next run.

Collection is deliberately not implemented yet. This module makes no API
calls and does not change files.
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] != "update":
        print("Usage: python -m topical_map.serps update")
        return 0

    print("SERP collection is not implemented yet; no files were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
