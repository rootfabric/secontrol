#!/usr/bin/env python3
"""Unified CLI for managing se-worker programs.

Subcommands:
    programs [-r|--running]                list programs (or only running)
    files     --program NAME_OR_UUID       list files inside a program
    logs      --program NAME_OR_UUID       tail logs of last/current run
    upload    --program NAME_OR_UUID       upload one or more files
    run       --program NAME_OR_UUID       start the program
              --entry FILENAME              on a grid
              --grid LABEL_OR_ID
              [--params JSON]
    stop      --program NAME_OR_UUID       stop the program
    create    --program NAME               create a new empty program

Program can be referenced by exact UUID, exact name, or unique substring
of name (case-insensitive). If multiple programs match, the tool errors
out instead of silently picking one.

All commands need SE_WORKER_INSTANCE_UUID (or --instance-uuid).
Exit codes:
    0 - success
    1 - user error (bad args, no match, etc.)
    2 - remote/network error
    3 - worker error (run/upload reported failure)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[5]
WORKER_API_PATH = REPO_ROOT / "examples" / "organized" / "worker"
if str(WORKER_API_PATH) not in sys.path:
    sys.path.insert(0, str(WORKER_API_PATH))

try:
    from WorkerApi import WorkerApiClient  # type: ignore
except Exception as exc:  # noqa: BLE001
    print(f"error: cannot import WorkerApiClient: {exc}", file=sys.stderr)
    sys.exit(2)


DEFAULT_BASE_URL = os.getenv(
    "SE_WORKER_BASE_URL", "https://www.outenemy.ru/se/worker-controller"
)


# ---------------------------------------------------------------------------
# Program resolution helpers
# ---------------------------------------------------------------------------

def _resolve_program(
    client: WorkerApiClient, ref: str
) -> tuple[Optional[str], Optional[str]]:
    """Return (uuid, name) for a program reference.

    ref can be:
      - exact UUID (used as-is)
      - exact program name
      - unique substring of a program name (case-insensitive)

    Returns (None, None) if nothing matches or more than one matches.
    """
    ref = ref.strip()
    if not ref:
        return None, None

    programs = client.get_programs() or {}
    items = programs.get("items", []) or []

    by_uuid = {p.get("uuid"): p for p in items if p.get("uuid")}

    if ref in by_uuid:
        p = by_uuid[ref]
        return ref, p.get("name") or ""

    ref_lower = ref.lower()
    exact_name = [p for p in items if (p.get("name") or "") == ref]
    if exact_name:
        p = exact_name[0]
        return p.get("uuid"), p.get("name") or ""

    partial = [
        p for p in items if ref_lower in (p.get("name") or "").lower()
    ]
    if len(partial) == 1:
        p = partial[0]
        return p.get("uuid"), p.get("name") or ""

    return None, None


def _load_params(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    raw = raw.strip()
    if not raw:
        return {}
    if raw.startswith("@"):
        path = Path(raw[1:])
        if not path.exists():
            raise ValueError(f"params file not found: {path}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"params file is not valid JSON: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--params is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("--params must be a JSON object")
    return parsed


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _print_programs(items: list[dict], running_only: bool, as_json: bool) -> None:
    rows: list[dict] = []
    for p in items:
        status = p.get("status") or ("running" if p.get("current_run") else "stopped")
        if running_only and status != "running":
            continue
        last_run = p.get("current_run") or p.get("last_run") or {}
        last_grid = p.get("last_grid_label") or last_run.get("grid_label") or ""
        last_file = last_run.get("filename") or ""
        rows.append(
            {
                "uuid": p.get("uuid"),
                "name": p.get("name"),
                "status": status,
                "last_grid": last_grid,
                "last_file": last_file,
                "run_id": last_run.get("run_id"),
            }
        )
    if as_json:
        print(json.dumps({"items": rows, "count": len(rows)}, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("(no programs)")
        return
    for r in rows:
        print(
            f"{r['uuid']}  {r['status']:<8}  {r['name']}  "
            f"grid={r['last_grid'] or '-'}  entry={r['last_file'] or '-'}"
        )


def cmd_programs(args: argparse.Namespace) -> int:
    client = WorkerApiClient(
        base_url=args.base_url, instance_uuid=args.instance_uuid
    )
    programs = client.get_programs() or {}
    items = programs.get("items", []) or []
    _print_programs(items, running_only=args.running, as_json=args.json)
    return 0


def cmd_files(args: argparse.Namespace) -> int:
    client = WorkerApiClient(
        base_url=args.base_url, instance_uuid=args.instance_uuid
    )
    uuid, name = _resolve_program(client, args.program)
    if not uuid:
        print(
            f"error: program {args.program!r} not found (or ambiguous)",
            file=sys.stderr,
        )
        return 1
    files = client.list_program_files(uuid)
    if files is None:
        return 2
    print(f"# program: {name}  uuid={uuid}")
    if isinstance(files, dict) and "items" in files:
        files = files["items"]
    if not files:
        print("(empty)")
        return 0
    if args.json:
        print(json.dumps(files, ensure_ascii=False, indent=2))
        return 0
    if isinstance(files[0], dict):
        for f in files:
            size = f.get("size", "?")
            mtime = f.get("mtime", "?")
            print(f"  {f.get('name'):<40}  size={size}  mtime={mtime}")
    else:
        for name in files:
            print(f"  {name}")
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    client = WorkerApiClient(
        base_url=args.base_url, instance_uuid=args.instance_uuid
    )
    uuid, name = _resolve_program(client, args.program)
    if not uuid:
        print(f"error: program {args.program!r} not found", file=sys.stderr)
        return 1
    tail = args.tail_bytes if args.tail_bytes is not None else 8000
    log = client.get_program_logs(uuid, tail_bytes=tail)
    if log is None:
        return 2
    if args.follow and args.follow > 0:
        seen_len = 0
        for _ in range(args.follow):
            time.sleep(max(0.2, args.interval))
            log = client.get_program_logs(uuid, tail_bytes=tail) or log
            new_chunk = log[seen_len:]
            if new_chunk:
                sys.stdout.write(new_chunk)
                sys.stdout.flush()
                seen_len = len(log)
        return 0
    print(f"# program: {name}  uuid={uuid}  tail={tail}")
    print(log)
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    client = WorkerApiClient(
        base_url=args.base_url, instance_uuid=args.instance_uuid
    )
    uuid, name = _resolve_program(client, args.program)
    if not uuid:
        print(f"error: program {args.program!r} not found", file=sys.stderr)
        return 1
    paths = [Path(p) for p in args.files]
    missing = [p for p in paths if not p.exists()]
    if missing:
        print("error: missing files:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        return 1
    print(f"# uploading {len(paths)} file(s) to {name} ({uuid})")
    ok_all = True
    for p in paths:
        size = p.stat().st_size
        print(f"  uploading {p.name} ({size} bytes)", end=" ... ", flush=True)
        ok = client.upload_files(uuid, [str(p)])
        if ok:
            print("ok")
        else:
            ok_all = False
            print("FAILED")
    return 0 if ok_all else 3


def cmd_run(args: argparse.Namespace) -> int:
    client = WorkerApiClient(
        base_url=args.base_url, instance_uuid=args.instance_uuid,
        timeout=120.0, max_retries=5, retry_delay=2.0,
    )
    uuid, name = _resolve_program(client, args.program)
    if not uuid:
        print(f"error: program {args.program!r} not found", file=sys.stderr)
        return 1
    try:
        params = _load_params(args.params)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"# starting {name} ({uuid}) on grid {args.grid} with entry {args.entry}")
    if params:
        print(f"# params: {json.dumps(params, ensure_ascii=False)}")
    info = client.run_program(
        program_uuid=uuid,
        filename=args.entry,
        grid_id=args.grid,
        params=params,
    )
    if not info:
        print("error: run_program returned no info", file=sys.stderr)
        return 2
    run = info.get("run") or info
    rid = run.get("run_id") or run.get("uuid")
    pid = run.get("pid")
    print(f"# run_id: {rid}  pid: {pid}  status: {run.get('status')}")
    print(f"# log_path: {run.get('log_path')}")
    print(f"# started_at: {run.get('started_at')}")
    if args.wait and args.wait > 0:
        time.sleep(args.wait)
        log = client.get_program_logs(uuid, tail_bytes=args.tail_bytes or 8000) or ""
        print()
        print("=== logs ===")
        print(log)
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    client = WorkerApiClient(
        base_url=args.base_url, instance_uuid=args.instance_uuid
    )
    uuid, name = _resolve_program(client, args.program)
    if not uuid:
        print(f"error: program {args.program!r} not found", file=sys.stderr)
        return 1
    print(f"# stopping {name} ({uuid})")
    ok = client.stop_program(uuid)
    if not ok:
        print("error: stop failed", file=sys.stderr)
        return 2
    print("ok")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    client = WorkerApiClient(
        base_url=args.base_url, instance_uuid=args.instance_uuid
    )
    created = client.create_program(args.program)
    if not created:
        print("error: create_program failed", file=sys.stderr)
        return 2
    uuid = created.get("uuid") or created.get("id")
    print(f"# created program: {args.program}  uuid={uuid}")
    return 0


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="worker controller base URL "
        "(default: $SE_WORKER_BASE_URL or https://www.outenemy.ru/se/worker-controller)",
    )
    parser.add_argument(
        "--instance-uuid",
        default=os.getenv("SE_WORKER_INSTANCE_UUID"),
        help="worker instance UUID (default: $SE_WORKER_INSTANCE_UUID)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="worker_cli",
        description="Manage se-worker programs (list, upload, run, logs, stop).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # programs
    p = sub.add_parser("programs", help="list all programs")
    _common(p)
    p.add_argument("-r", "--running", action="store_true", help="only running")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.set_defaults(func=cmd_programs)

    # files
    p = sub.add_parser("files", help="list files inside a program")
    _common(p)
    p.add_argument("--program", required=True, help="program name/UUID/substring")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_files)

    # logs
    p = sub.add_parser("logs", help="tail logs of a program")
    _common(p)
    p.add_argument("--program", required=True, help="program name/UUID/substring")
    p.add_argument(
        "--tail-bytes", type=int, default=8000,
        help="bytes to fetch (default 8000)",
    )
    p.add_argument(
        "--follow", type=int, default=0, metavar="N",
        help="poll logs N times after the first read",
    )
    p.add_argument(
        "--interval", type=float, default=2.0,
        help="poll interval seconds when --follow>0 (default 2.0)",
    )
    p.set_defaults(func=cmd_logs)

    # upload
    p = sub.add_parser("upload", help="upload files to a program")
    _common(p)
    p.add_argument("--program", required=True, help="program name/UUID/substring")
    p.add_argument("files", nargs="+", help="local file paths to upload")
    p.set_defaults(func=cmd_upload)

    # run
    p = sub.add_parser("run", help="start a program on a grid")
    _common(p)
    p.add_argument("--program", required=True, help="program name/UUID/substring")
    p.add_argument("--entry", required=True, help="entry filename (e.g. my_app.py)")
    p.add_argument("--grid", required=True, help="grid label or numeric id")
    p.add_argument(
        "--params", default=None,
        help='JSON object or @file with params (passed to WORKER_PARAMS)',
    )
    p.add_argument(
        "--wait", type=float, default=0.0,
        help="seconds to sleep before fetching initial logs",
    )
    p.add_argument("--tail-bytes", type=int, default=8000)
    p.set_defaults(func=cmd_run)

    # stop
    p = sub.add_parser("stop", help="stop a running program")
    _common(p)
    p.add_argument("--program", required=True, help="program name/UUID/substring")
    p.set_defaults(func=cmd_stop)

    # create
    p = sub.add_parser("create", help="create a new program (rarely needed)")
    _common(p)
    p.add_argument("--program", required=True, help="program name (must be unique)")
    p.set_defaults(func=cmd_create)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.instance_uuid:
        print(
            "error: --instance-uuid or $SE_WORKER_INSTANCE_UUID is required",
            file=sys.stderr,
        )
        return 1
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())