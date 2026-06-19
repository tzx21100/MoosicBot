from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from moosicbot.config import Settings, load_settings
from moosicbot.music import MusicCog


class MoosicBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.voice_states = True
        intents.message_content = True

        super().__init__(
            command_prefix=settings.command_prefix,
            intents=intents,
            help_command=None,
        )
        self.settings = settings

    async def setup_hook(self) -> None:
        await self.add_cog(MusicCog(self, self.settings))

        try:
            if self.settings.discord_guild_id:
                guild = discord.Object(id=self.settings.discord_guild_id)
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
                logging.info("Cleared slash commands for guild %s; using prefix commands only", guild.id)
            else:
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                logging.info("Cleared global slash commands; using prefix commands only")
        except discord.HTTPException:
            logging.warning("Could not clear old slash commands; prefix commands are still enabled", exc_info=True)

    async def on_ready(self) -> None:
        if self.user:
            logging.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="!play"))


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = load_settings()
    bot = MoosicBot(settings)
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
