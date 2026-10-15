"""Print the score breakdown of the newest eval log in a directory (or a given .eval file).

python -m taskqa.show runs/logs/grade
"""

import sys
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log


def newest(path: Path) -> str:
    if path.is_file():
        return str(path)
    logs = list_eval_logs(str(path))
    if not logs:
        raise SystemExit(f"no eval logs in {path}")
    return max(logs, key=lambda info: info.mtime or 0).name


def main() -> int:
    target = newest(Path(sys.argv[1] if len(sys.argv) > 1 else "runs/logs/grade"))
    log = read_eval_log(target)
    print(f"log: {target}  status: {log.status}")
    for sample in log.samples or []:
        print(f"\n== sample {sample.id}")
        for name, score in (sample.scores or {}).items():
            print(f"[{name}]")
            print(score.explanation or "")
            if isinstance(score.value, dict):
                print("  " + ", ".join(f"{k}={v}" for k, v in score.value.items()))
        if sample.error:
            print(f"error: {sample.error.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
