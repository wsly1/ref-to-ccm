import sys

from .cli import main as cli_main
from .gui import main as gui_main

if __name__ == "__main__":
    if len(sys.argv) == 1 or "--gui" in sys.argv:
        raise SystemExit(gui_main())
    raise SystemExit(cli_main())
