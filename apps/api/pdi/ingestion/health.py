import time
from pathlib import Path


def main() -> None:
    path = Path("/tmp/pdi-worker-alive")
    if not path.is_file() or time.time() - path.stat().st_mtime > 30:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
