"""Compatibility entry point. The command is `python -m stead`."""

import sys

from ctx.cli import main

if __name__ == "__main__":
    print("The command is stead. The old module name still works.", file=sys.stderr)
    raise SystemExit(main())
