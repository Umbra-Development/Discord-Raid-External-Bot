from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from umbra_bot import config
from umbra_bot.utils import NotOwner, is_owner

if TYPE_CHECKING:
    from umbra_bot.bot import SyraBot


class UtilCog(commands.Cog):
    """Owner utilities and runtime configuration management."""

    def __init__(self, bot: "SyraBot") -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        config.reload_config()

    @app_commands.command(
        name="reloadconfig",
        description="Reload the application configuration from disk.",
    )
    @is_owner()
    async def reload_config_command(
        self, interaction: discord.Interaction
    ) -> None:
        try:
            config.reload_config()
        except (KeyError, TypeError, ValueError, OSError) as error:
            await interaction.response.send_message(
                f"Configuration reload failed: {error}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Configuration reloaded successfully.",
            ephemeral=True,
        )

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, NotOwner):
            await interaction.response.send_message(str(error), ephemeral=True)
            return
        raise error


async def setup(bot: "SyraBot") -> None:
    await bot.add_cog(UtilCog(bot))
