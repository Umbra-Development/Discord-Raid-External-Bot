"""Terminal control surface for the Umbra bot."""


def main() -> None:
    from .app import UmbraTUI

    UmbraTUI().run()


__all__ = ["main"]
