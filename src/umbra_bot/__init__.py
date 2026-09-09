PACKAGED_BOT_ARGUMENT = "--umbra-bot-child"


def main() -> None:
    from .bot import SyraBot
    from .config import token

    bot = SyraBot()
    bot.run(token)
