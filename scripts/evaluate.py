"""从仓库根目录运行 Vidferry 评测。"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
