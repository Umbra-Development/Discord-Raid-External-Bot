import math
import time
from collections.abc import Callable
from typing import Any, TypedDict, cast

import discord
from discord import app_commands
from discord.ext import commands

from umbra_bot.config import load_config


class CooldownUsage(TypedDict):
    uses: list[float]
    blocked_until: float | None


class ConfiguredCooldown(app_commands.CheckFailure):
    """Raised when a user is blocked by the configured cooldown."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Try again in {retry_after} seconds.")


class NotOwner(app_commands.CheckFailure):
    """Raised when an application command requires the bot owner."""

    def __init__(self) -> None:
        super().__init__("This command can only be used by the bot owner.")


def check_cooldown() -> Callable[[Any], Any]:
    """Create a per-user slash-command cooldown using the JSON5 settings.

    The settings are read at invocation time, so edits made through the GUI or
    a reload command apply without recreating this decorator.
    """

    async def predicate(interaction: discord.Interaction) -> bool:
        settings = load_config()["basic_config"]
        max_uses = max(1, int(settings["max_uses"]))
        window_seconds = max(1, int(settings["wait_seconds"]))
        block_seconds = max(1, int(settings["b_seconds"]))

        bot = interaction.client
        usage_by_user = getattr(bot, "user_usage", None)
        if usage_by_user is None:
            usage_by_user = {}
            setattr(bot, "user_usage", usage_by_user)

        now = time.monotonic()
        usage = cast(
            CooldownUsage,
            usage_by_user.setdefault(
                interaction.user.id,
                {"uses": [], "blocked_until": None},
            ),
        )

        blocked_until = usage["blocked_until"]
        if blocked_until is not None:
            if now < blocked_until:
                raise ConfiguredCooldown(math.ceil(blocked_until - now))
            usage["blocked_until"] = None
            usage["uses"].clear()

        usage["uses"] = [
            used_at
            for used_at in usage["uses"]
            if now - used_at < window_seconds
        ]

        if len(usage["uses"]) >= max_uses:
            usage["blocked_until"] = now + block_seconds
            raise ConfiguredCooldown(block_seconds)

        usage["uses"].append(now)
        return True

    return app_commands.check(predicate)


def is_owner() -> Callable[[Any], Any]:
    """Create a slash-command check restricted to the bot application owner."""

    async def predicate(interaction: discord.Interaction) -> bool:
        bot = interaction.client
        if not isinstance(bot, commands.Bot) or not await bot.is_owner(
            interaction.user
        ):
            raise NotOwner()
        return True

    return app_commands.check(predicate)
