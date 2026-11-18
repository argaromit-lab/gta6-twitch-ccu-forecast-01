"""Run Node's deterministic process benchmark and historical cross-validation."""
import subprocess
from pathlib import Path

if __name__ == "__main__":
    raise SystemExit(subprocess.call(["node", "verify-node.cjs"],
                                    cwd=Path(__file__).resolve().parent))
