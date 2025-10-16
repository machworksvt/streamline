from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Dict, List


def collect() -> Dict[str, object]:
    env = {key: value for key, value in os.environ.items()}
    sys_path: List[str] = list(sys.path)
    return {
        "platform": platform.platform(),
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "prefix": sys.prefix,
            "base_prefix": getattr(sys, "base_prefix", None),
            "path": sys_path,
        },
        "cwd": str(Path.cwd()),
        "env": env,
    }


def main() -> None:
    data = collect()
    json.dump(data, sys.stdout, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
