"""
self_heal.py — Analiza el código y DB, genera plan de mejora. Corre 2x/dia via launchd.

Modos:
  python3 self_heal.py           -> Solo analisis, genera plan en logs/
  python3 self_heal.py --apply   -> Aplica auto-fix (ruff --fix) + tests
"""

import argparse
import contextlib
import logging
import logging.handlers
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .config import now_venezuela

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("self_heal")

BASE_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = BASE_DIR.parent.resolve()
LOG_DIR = BASE_DIR / "logs"
PLAN_FILE = LOG_DIR / "self_heal_plan.md"
DB_PATH = BASE_DIR / "p2p_sentinel.db"
HEAL_LOG = LOG_DIR / "self_heal.log"

LOG_DIR.mkdir(parents=True, exist_ok=True)

_VALID_IDENT = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

def _safe_ident(name: str) -> str:
    if not name or not _VALID_IDENT.match(name):
        raise ValueError(f"Identificador SQL inválido: {name!r}")
    return name

_fh = logging.handlers.RotatingFileHandler(
    HEAL_LOG, maxBytes=1024 * 1024, backupCount=3
)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_fh)


# --- Analizadores -------------------------------------------------------------

def _run(cmd: list, cwd=None, timeout=60) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd or PROJECT_DIR, timeout=timeout,
            check=False,  # explicito (I4.05): el caller maneja exit codes
        )
    except subprocess.TimeoutExpired as e:
        out = str(e.stdout or "")
        err = str(e.stderr or "")
        return subprocess.CompletedProcess(cmd, -1, out + "\n[TIMEOUT]", err)


def _section(name: str) -> str:
    return f"\n## {name}\n\n"


def check_ruff() -> dict:
    r = _run(["python3", "-m", "ruff", "check", str(BASE_DIR)], timeout=30)
    count = 0
    fixable = 0
    for line in r.stdout.splitlines():
        if "Found" in line and ("error" in line or "errors" in line):
            parts = line.strip().split()
            with contextlib.suppress(ValueError, IndexError):
                count = int(parts[1])
        if "[*]" in line:
            fixable += 1
    return {
        "count": count,
        "fixable_count": fixable,
        "output": r.stdout + r.stderr,
    }


def check_mypy() -> dict:
    py_files = [str(p) for p in sorted(BASE_DIR.glob("*.py"))]
    if not py_files:
        return {"count": 0, "output": "No .py files found"}
    r = _run([
        "python3", "-m", "mypy",
        "--ignore-missing-imports", "--follow-imports=skip",
    ] + py_files, timeout=30)
    errors = sum(1 for line in r.stdout.splitlines()
                 if "error:" in line and ".py:" in line)
    return {"count": errors, "output": r.stdout + r.stderr}


def check_tests() -> dict:
    r = _run([
        "python3", "-m", "pytest", str(PROJECT_DIR / "tests"), "-v", "--tb=short",
    ], timeout=120)
    passed = failed = 0
    for raw_line in r.stdout.splitlines():
        line = raw_line.strip()
        if not line.startswith("=="):
            continue
        parts = line.split()
        try:
            idx_p = parts.index("passed")
            passed = int(parts[idx_p - 1])
        except (ValueError, IndexError):
            pass
        try:
            idx_f = parts.index("failed")
            failed = int(parts[idx_f - 1])
        except (ValueError, IndexError):
            pass
    return {"passed": passed, "failed": failed, "output": r.stdout + r.stderr}


def check_db() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "heartbeat": None,
        "p2p_history_count": 0,
        "global_p2p_history_count": 0,
        "p2p_ads_buy": 0,
        "p2p_ads_sell": 0,
        "error": None,
    }
    if not DB_PATH.exists():
        info["error"] = "DB file not found"
        return info
    conn = None
    try:
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("SELECT * FROM worker_heartbeat WHERE id = 1")
        hb = cur.fetchone()
        if hb:
            info["heartbeat"] = {
                "timestamp": hb["timestamp"],
                "status": hb["status"],
                "cycle_count": hb["cycle_count"],
                "last_error": hb["last_error"],
            }

        for tbl in ["p2p_history", "global_p2p_history"]:
            safe_tbl = _safe_ident(tbl)
            cur.execute(f"SELECT COUNT(*) as cnt FROM {safe_tbl}")
            info[f"{tbl}_count"] = cur.fetchone()["cnt"]

        cur.execute("SELECT trade_type, COUNT(*) as cnt FROM p2p_ads GROUP BY trade_type")
        for row in cur.fetchall():
            key = "p2p_ads_buy" if row["trade_type"] == "BUY" else "p2p_ads_sell"
            info[key] = row["cnt"]
    except Exception as e:
        info["error"] = str(e)
    finally:
        if conn:
            conn.close()
    return info


def plan_exists() -> dict:
    if not PLAN_FILE.exists():
        return {"exists": False}
    mtime = datetime.fromtimestamp(PLAN_FILE.stat().st_mtime, tz=timezone.utc)
    age = datetime.now(timezone.utc) - mtime
    return {"exists": True, "age_seconds": age.total_seconds(), "age_str": str(age).split(".")[0]}


# --- Generar plan -------------------------------------------------------------

def generate_plan(ruff, mypy, tests, db, prev) -> str:
    lines = []
    lines.append(f"# Self-Heal Plan — {now_venezuela().strftime('%Y-%m-%d %H:%M')} VET")
    lines.append("")
    lines.append("Generado por `self_heal.py`. Revisa este plan antes de aplicar cambios.")
    lines.append("")

    # Resume
    lines.append(_section("Resumen"))
    ruff_icon = "OK" if ruff["count"] == 0 else "FIX" if ruff["fixable_count"] > 0 else "ERR"
    mypy_icon = "OK" if mypy["count"] == 0 else "WARN"
    tests_icon = "OK" if tests["failed"] == 0 else "FAIL"

    lines.append("| Componente | Estado | Detalle |")
    lines.append("|-----------|--------|---------|")
    lines.append(f"| Ruff       | {ruff_icon}     | {ruff['count']} errores ({ruff['fixable_count']} auto-fix) |")
    lines.append(f"| Mypy       | {mypy_icon}     | {mypy['count']} errores |")
    lines.append(f"| Tests      | {tests_icon}     | {tests['passed']} passed, {tests['failed']} failed |")
    lines.append("")

    # DB Health
    lines.append(_section("DB Health"))
    hb = db.get("heartbeat")
    if hb:
        lines.append(f"- **Worker**: `{hb['status']}`, ciclos `{hb['cycle_count']}` ({_time_ago(hb['timestamp'])})")
        if hb.get("last_error"):
            lines.append(f"- **Ultimo error**: `{hb['last_error']}`")
    else:
        lines.append("- **Worker**: Sin heartbeat en BD")

    lines.append(f"- **p2p_history**: `{db['p2p_history_count']:,}` filas")
    lines.append(f"- **global_p2p_history**: `{db['global_p2p_history_count']:,}` filas")
    lines.append(f"- **p2p_ads**: BUY(`{db['p2p_ads_buy']}`) SELL(`{db['p2p_ads_sell']}`)")

    if db.get("error"):
        lines.append(f"- WARN: `{db['error']}`")
    lines.append("")

    # Auto-fix
    if ruff["fixable_count"] > 0:
        lines.append(_section("Auto-fix disponibles"))
        lines.append("Ejecuta `--apply` para aplicar:\n")
        for line in ruff["output"].splitlines():
            if "[*]" in line:
                lines.append(f"  - `{line.strip()}`")
        lines.append("")
        lines.append(f"Para aplicar:\n  python3 {BASE_DIR.name}/self_heal.py --apply")
        lines.append("")

    # Mypy
    if mypy["count"] > 0:
        lines.append(_section("Mypy warnings"))
        for line in mypy["output"].splitlines()[-20:]:
            if "error:" in line and ".py:" in line:
                lines.append(f"  - {line.strip()}")
        lines.append("")

    # Previous
    if prev["exists"]:
        lines.append(_section("Plan anterior"))
        lines.append(f"Ultimo plan generado hace {prev['age_str']}")
        lines.append("")

    return "\n".join(lines)


def _time_ago(ts_str: str) -> str:
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts_str
    now = now_venezuela().replace(tzinfo=None)
    delta = now - dt
    if delta.days > 0:
        return f"hace {delta.days}d"
    if delta.seconds >= 3600:
        return f"hace {delta.seconds // 3600}h"
    if delta.seconds >= 60:
        return f"hace {delta.seconds // 60}m"
    return f"hace {delta.seconds}s"


# --- Apply -------------------------------------------------------------------

def apply_fixes():
    logger.info("Aplicando auto-fixes...")
    r = _run(["python3", "-m", "ruff", "check", "--fix", str(BASE_DIR)], timeout=30)

    changed = [
        line.strip()
        for line in r.stdout.splitlines()
        if "->" in line and "Fixed" in line
    ]

    logger.info(f"Ruff result: {r.stdout.strip()}")
    if r.stderr:
        logger.warning(f"Ruff stderr: {r.stderr.strip()}")

    print(f"Archivos modificados ({len(changed)}):" if changed else "Sin cambios que aplicar.")
    for c in changed:
        print(f"  {c}")

    print("\nCorriendo tests para verificar...")
    tests = check_tests()
    if tests["failed"] == 0:
        print(f"OK: {tests['passed']} passed, {tests['failed']} failed")
        logger.info(f"Apply OK: {len(changed)} archivos, {tests['passed']} tests passed")
        return True
    else:
        print(f"FALLOS: {tests['passed']} passed, {tests['failed']} failed")
        print(tests["output"][:2000])
        logger.error("Apply FAILED: tests rotos")
        return False


# --- Main --------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Self-heal analyzer for P2P Sentinel")
    parser.add_argument("--apply", action="store_true", help="Apply auto-fixes")
    args = parser.parse_args()

    # Desactivar en producción (filesystem read-only, no dev tools)
    if os.environ.get("ENVIRONMENT", "development").lower() == "production":
        logger.info("Self-heal desactivado en producción (ENVIRONMENT=production)")
        sys.exit(0)

    if args.apply:
        ok = apply_fixes()
        sys.exit(0 if ok else 1)

    logger.info("=== Self-Heal Analysis ===")

    ruff = check_ruff()
    mypy = check_mypy()
    tests = check_tests()
    db = check_db()
    prev = plan_exists()

    plan = generate_plan(ruff, mypy, tests, db, prev)

    PLAN_FILE.write_text(plan)
    logger.info(f"Plan generado: {PLAN_FILE}")

    print(plan)

    if ruff["fixable_count"] > 0:
        print(f"\nDisponibles: {ruff['fixable_count']} auto-fix. Corre: python3 self_heal.py --apply")


if __name__ == "__main__":
    main()
