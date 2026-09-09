"""PyInstaller entry point for the combined Umbra application."""

import sys

from umbra_bot import PACKAGED_BOT_ARGUMENT


def main() -> None:
    if PACKAGED_BOT_ARGUMENT in sys.argv[1:]:
        sys.argv.remove(PACKAGED_BOT_ARGUMENT)
        from umbra_bot import main as run_bot

        run_bot()
        return

    from umbra_gui import main as run_gui

    run_gui()


if __name__ == "__main__":
    main()
