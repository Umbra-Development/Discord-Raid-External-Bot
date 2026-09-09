import discord
from discord import app_commands
from discord.ext import commands

from typing import TYPE_CHECKING

from umbra_bot import config
from umbra_bot.utils import ConfiguredCooldown, check_cooldown

if TYPE_CHECKING:
    from umbra_bot.bot import SyraBot

class RaidCog(commands.Cog):
    def __init__(self, bot: "SyraBot") -> None:
        self.bot = bot

    @app_commands.command(
        name="raid",
        description="sends a set of raid messages"
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(
        guilds=True,
        dms=True,
        private_channels=True,
    )
    @check_cooldown()
    async def raid(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(config.pm)
        print(f"Raiding a server")
        for i in range(5):
            await interaction.followup.send(config.pm)
        print(f"Raided server")

    @app_commands.command(
        name="pingraid",
        description="use if @everyone enabled"
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(
        guilds=True,
        dms=True,
        private_channels=True,
    )
    @check_cooldown()
    async def raid1(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(config.pingpm)
        print(f"Raiding a server")
        for i in range(5):
            await interaction.followup.send(config.pingpm)
        print(f"Successfully raided")

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, ConfiguredCooldown):
            minutes, seconds = divmod(error.retry_after, 60)
            await interaction.response.send_message(
                f"You are on cooldown. Try again in {minutes}m {seconds}s.",
                ephemeral=True,
            )
            return
        raise error


async def setup(bot: "SyraBot") -> None:
    await bot.add_cog(RaidCog(bot))
