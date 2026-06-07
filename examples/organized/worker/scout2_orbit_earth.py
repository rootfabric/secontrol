from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_URL = os.getenv("SECONTROL_REPO_URL", "https://github.com/rootfabric/secontrol.git")
REPO_REF = os.getenv("SECONTROL_REPO_REF", "main")
REPO_DIR = Path(os.getenv("SECONTROL_REPO_DIR", "/app/workspace/secontrol_runtime_repo")).resolve()
SCRIPT_RELATIVE_PATH = Path("examples/space_flight/orbit_earth.py")


def get_worker_params() -> dict[str, Any]:
    module_params = globals().get("params")
    if isinstance(module_params, dict):
        return dict(module_params)

    raw = os.getenv("WORKER_PARAMS", "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"WORKER_PARAMS is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"WORKER_PARAMS must be a JSON object, got {type(parsed).__name__}")

    return parsed


def run_git(args: list[str], *, cwd: Path | None = None, insecure: bool = False) -> None:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    if insecure:
        env["GIT_SSL_NO_VERIFY"] = "true"
    print("[scout2_orbit] git:", " ".join(args), flush=True)
    subprocess.run(["git", *args], cwd=str(cwd) if cwd else None, env=env, check=True)


def run_with_tls_fallback(action) -> None:
    try:
        action(False)
        return
    except subprocess.CalledProcessError:
        allow_fallback = os.getenv("SECONTROL_SSL_NO_VERIFY_FALLBACK", "1").strip().lower()
        if allow_fallback not in {"1", "true", "yes", "on"}:
            raise

    print(
        "[scout2_orbit] WARNING: git TLS verification failed; retrying with GIT_SSL_NO_VERIFY=true",
        flush=True,
    )
    action(True)


def sync_secontrol_repo() -> Path:
    script_path = REPO_DIR / SCRIPT_RELATIVE_PATH
    if script_path.exists():
        print(f"[scout2_orbit] using existing secontrol repo: {REPO_DIR}", flush=True)
        return script_path

    if not shutil.which("git"):
        raise RuntimeError("git is not installed in worker container")

    REPO_DIR.parent.mkdir(parents=True, exist_ok=True)

    if (REPO_DIR / ".git").exists():
        def fetch(insecure: bool) -> None:
            run_git(["remote", "set-url", "origin", REPO_URL], cwd=REPO_DIR, insecure=insecure)
            run_git(["fetch", "--depth", "1", "origin", REPO_REF], cwd=REPO_DIR, insecure=insecure)
            run_git(["reset", "--hard", "FETCH_HEAD"], cwd=REPO_DIR, insecure=insecure)
            run_git(["clean", "-fdx"], cwd=REPO_DIR, insecure=insecure)

        run_with_tls_fallback(fetch)
    else:
        if REPO_DIR.exists():
            shutil.rmtree(REPO_DIR)

        def clone(insecure: bool) -> None:
            run_git(["clone", "--depth", "1", "--branch", REPO_REF, REPO_URL, str(REPO_DIR)], insecure=insecure)

        run_with_tls_fallback(clone)

    if not script_path.exists():
        raise FileNotFoundError(f"orbit script not found: {script_path}")

    return script_path


def build_orbit_argv(script_path: Path, p: dict[str, Any]) -> list[str]:
    # Prefer user-level route parameter `grid`.  Do not use injected grid_id as a
    # fallback before grid_label: it may be a controller binding and not the ship
    # the operator asked for.
    grid = str(
        p.get("grid")
        or p.get("grid_name")
        or p.get("target_grid")
        or p.get("grid_label")
        or "skynet-scout2"
    )
    center_distance_km = float(p.get("center_distance_km", p.get("center-distance-km", 90)))
    marker_step_km = float(p.get("marker_step_km", p.get("marker-step-km", 5)))

    argv = [
        str(script_path),
        "--grid",
        grid,
        "--center-distance-km",
        str(center_distance_km),
        "--marker-step-km",
        str(marker_step_km),
    ]

    orbit_tilt_deg = p.get("orbit_tilt_deg", p.get("orbit-tilt-deg"))
    if orbit_tilt_deg is not None:
        argv.extend(["--orbit-tilt-deg", str(float(orbit_tilt_deg))])

    orbit_normal = p.get("orbit_normal", p.get("orbit-normal"))
    if orbit_normal is not None:
        argv.extend(["--orbit-normal", str(orbit_normal)])

    speed = p.get("speed", p.get("speed_mps"))
    if speed is not None:
        argv.extend(["--speed", str(float(speed))])

    return argv


def main() -> None:
    p = get_worker_params()
    print(f"[scout2_orbit] params: {json.dumps(p, ensure_ascii=False)}", flush=True)

    script_path = sync_secontrol_repo()
    repo_src = str(REPO_DIR / "src")
    repo_root = str(REPO_DIR)
    if repo_src not in sys.path:
        sys.path.insert(0, repo_src)
    if repo_root not in sys.path:
        sys.path.insert(1, repo_root)

    sys.argv = build_orbit_argv(script_path, p)
    print("[scout2_orbit] executing:", " ".join(sys.argv), flush=True)
    runpy.run_path(str(script_path), run_name="__main__")


if __name__ == "__main__":
    main()
