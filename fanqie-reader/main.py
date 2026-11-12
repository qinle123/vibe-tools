#!/usr/bin/env python3
import sys
from pathlib import Path

# 将当前目录加入 sys.path
root_dir = Path(__file__).parent.resolve()
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from fanqie_reader.cli import main

if __name__ == "__main__":
    main()
