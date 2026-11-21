"""Medisina API contract tool. Run from the project root, with the venv active:

    python portal-backend/contract.py pull                     # save a fresh swagger.json here
    python portal-backend/contract.py show "/doctors/search"   # print one path from the LIVE contract
    python portal-backend/contract.py check                    # app/medisina/operations.py vs the LIVE contract

The contract is refreshed in place whenever Medisina changes, so `show` and
`check` always download it fresh. `pull` updates the local swagger.json copy;
run it after a Medisina release and `git diff portal-backend/swagger.json`
shows exactly what changed.
"""
import argparse
import json
import sys
from pathlib import Path

import httpx  # already a backend dependency; ships its own CA certificates

CONTRACT_URL = "https://medisina-api-contracts-prod.s3.ap-south-2.amazonaws.com/swagger.json"
HERE = Path(__file__).resolve().parent
LOCAL_COPY = HERE / "swagger.json"
_METHODS = {"get", "post", "put", "patch", "delete"}


def fetch_contract(url: str = CONTRACT_URL) -> dict:
    resp = httpx.get(url, timeout=30, headers={"Cache-Control": "no-cache"})
    resp.raise_for_status()
    return resp.json()


def check_operations(spec: dict, operations) -> list[str]:
    """Return human-readable problems (empty list = everything matches)."""
    problems: list[str] = []
    paths = spec.get("paths", {})
    for op in operations:
        label = f"{op.method} {op.path}"
        item = paths.get(op.path)
        if item is None:
            problems.append(f"{label}: path no longer exists in the contract")
            continue
        operation = item.get(op.method.lower())
        if operation is None:
            available = ", ".join(m.upper() for m in item if m in _METHODS)
            problems.append(f"{label}: method not in contract (available: {available})")
            continue
        declared = {
            p.get("name")
            for p in [*item.get("parameters", []), *operation.get("parameters", [])]
            if p.get("in") == "query"
        }
        for q in op.query:
            if q not in declared:
                problems.append(f"{label}: query param '{q}' is not in the contract")
    return problems


def _cmd_pull(_args) -> int:
    spec = fetch_contract()
    LOCAL_COPY.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Saved {len(spec.get('paths', {}))} paths to {LOCAL_COPY}")
    return 0


def _cmd_show(args) -> int:
    item = fetch_contract().get("paths", {}).get(args.path)
    if item is None:
        print(f"{args.path} is not in the contract.")
        return 1
    print(json.dumps(item, indent=2))
    return 0


def _cmd_check(_args) -> int:
    sys.path.insert(0, str(HERE.parent))  # so `app.medisina` (the backend) is importable
    from app.medisina.operations import ALL_OPS

    spec = fetch_contract()
    problems = check_operations(spec, ALL_OPS)
    if problems:
        print(f"{len(problems)} problem(s) against the live contract:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: all {len(ALL_OPS)} operations in app/medisina/operations.py match "
          f"the live contract ({len(spec.get('paths', {}))} paths).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Medisina API contract tool")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pull", help="save a fresh swagger.json next to this script")
    show = sub.add_parser("show", help="print one path from the live contract")
    show.add_argument("path", help='e.g. "/doctors/{id}"')
    sub.add_parser("check", help="check app/medisina/operations.py against the live contract")
    args = parser.parse_args()
    return {"pull": _cmd_pull, "show": _cmd_show, "check": _cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
