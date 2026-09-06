import os
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web, ClientSession, ClientTimeout


# =========================================================
# CONFIG
# =========================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
MIGHTPULSE_API_KEY = os.getenv("MIGHTPULSE_API_KEY")

PORT = int(os.getenv("PORT", "10000"))

API_BASE = "https://api.mightpulse.com/v1"


# =========================================================
# CHECK CONFIG
# =========================================================

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

if not DISCORD_APPLICATION_ID:
    raise RuntimeError("DISCORD_APPLICATION_ID is missing")

if not MIGHTPULSE_API_KEY:
    raise RuntimeError("MIGHTPULSE_API_KEY is missing")


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("mightpulse-bot")


# =========================================================
# DISCORD
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    application_id=int(DISCORD_APPLICATION_ID)
)


# =========================================================
# MIGHTPULSE API
# =========================================================

class MightPulseAPI:

    def __init__(self, api_key):
        self.api_key = api_key
        self.session = None

    async def start(self):

        if self.session is not None:
            return

        self.session = ClientSession(
            timeout=ClientTimeout(total=60),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json"
            }
        )

    async def close(self):

        if self.session:

            await self.session.close()

            self.session = None

    async def get(
        self,
        endpoint,
        params=None
    ):

        await self.start()

        url = f"{API_BASE}{endpoint}"

        log.info(
            "GET %s",
            url
        )

        async with self.session.get(
            url,
            params=params
        ) as response:

            try:

                data = await response.json()

            except Exception:

                data = {
                    "error": await response.text()
                }

            log.info(
                "MightPulse HTTP %s",
                response.status
            )

            if response.status == 401:

                raise Exception(
                    "MightPulse API Key غير صحيح أو غير مصرح."
                )

            if response.status == 403:

                raise Exception(
                    "MightPulse رفض الطلب. "
                    "تأكد من صلاحية الـ API Key والخطة."
                )

            if response.status == 404:

                raise Exception(
                    "لم يتم العثور على البيانات المطلوبة."
                )

            if response.status == 429:

                raise Exception(
                    "تم الوصول إلى حد الطلبات في MightPulse."
                )

            if response.status >= 400:

                message = (
                    data.get("message")
                    or data.get("error")
                    or f"HTTP {response.status}"
                )

                raise Exception(
                    str(message)
                )

            return data


api = MightPulseAPI(
    MIGHTPULSE_API_KEY
)


# =========================================================
# HELPERS
# =========================================================

def get_value(
    data,
    key,
    default="N/A"
):

    if not isinstance(data, dict):
        return default

    result = data.get(key)

    if result is None or result == "":
        return default

    return str(result)


def format_number(value):

    if value is None:
        return "N/A"

    try:

        n = float(value)

        if n >= 1_000_000_000:
            return f"{n / 1_000_000_000:.2f}B"

        if n >= 1_000_000:
            return f"{n / 1_000_000:.2f}M"

        if n >= 1_000:
            return f"{n / 1_000:.1f}K"

        return f"{int(n):,}"

    except Exception:

        return str(value)


async def send_error(
    interaction,
    error
):

    message = f"❌ {error}"

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                message,
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                message,
                ephemeral=True
            )

    except Exception as send_error:

        log.error(
            "Error sending Discord error: %s",
            send_error
        )


# =========================================================
# PLAYER
# =========================================================

@bot.tree.command(
    name="player",
    description="Get a player from MightPulse"
)
@app_commands.describe(
    governor_id="Governor ID"
)
async def player(
    interaction: discord.Interaction,
    governor_id: str
):

    await interaction.response.defer()

    try:

        data = await api.get(
            f"/players/{governor_id}",
            {
                "include": "base,heroes,ranks,gov_gear"
            }
        )

        player_data = data.get(
            "player",
            data
        )

        if not isinstance(
            player_data,
            dict
        ):

            raise Exception(
                "MightPulse returned an unexpected player response."
            )

        alliance = (
            player_data.get("alliance")
            or {}
        )

        player_name = (
            player_data.get("nick_name")
            or player_data.get("name")
            or "Unknown Player"
        )

        embed = discord.Embed(
            title=f"👤 {player_name}",
            description=(
                "Governor ID: "
                f"`{get_value(player_data, 'governor_id', governor_id)}`"
            )
        )

        embed.add_field(
            name="🌍 Kingdom",
            value=get_value(
                player_data,
                "kid"
            ),
            inline=True
        )

        embed.add_field(
            name="⚡ Power",
            value=format_number(
                player_data.get("power")
            ),
            inline=True
        )

        embed.add_field(
            name="🏰 TC",
            value=get_value(
                player_data,
                "town_center_level"
            ),
            inline=True
        )

        embed.add_field(
            name="💎 VIP",
            value=get_value(
                player_data,
                "vip"
            ),
            inline=True
        )

        embed.add_field(
            name="⚔️ Kills",
            value=format_number(
                player_data.get("kills")
            ),
            inline=True
        )

        alliance_name = (
            alliance.get("name")
            or alliance.get("abbr")
            or "No Alliance"
        )

        embed.add_field(
            name="🛡️ Alliance",
            value=str(alliance_name),
            inline=False
        )

        avatar = player_data.get(
            "avatar_url"
        )

        if avatar:

            embed.set_thumbnail(
                url=avatar
            )

        await interaction.followup.send(
            embed=embed
        )

    except Exception as error:

        await send_error(
            interaction,
            error
        )


# =========================================================
# ALLIANCE
# =========================================================

@bot.tree.command(
    name="alliance",
    description="Get an alliance from MightPulse"
)
@app_commands.describe(
    kingdom_id="Kingdom ID",
    tag="Alliance tag"
)
async def alliance(
    interaction: discord.Interaction,
    kingdom_id: int,
    tag: str
):

    await interaction.response.defer()

    try:

        tag = tag.upper().strip()

        data = await api.get(
            f"/alliances/{kingdom_id}/{tag}",
            {
                "include": "info,roster"
            }
        )

        alliance_data = data.get(
            "alliance",
            data
        )

        members = (
            data.get("members")
            or data.get("roster")
            or []
        )

        embed = discord.Embed(
            title=(
                "🛡️ "
                f"{get_value(alliance_data, 'name', tag)}"
            ),
            description=(
                f"Kingdom: `{kingdom_id}`\n"
                f"Tag: `{tag}`"
            )
        )

        embed.add_field(
            name="⚡ Power",
            value=format_number(
                alliance_data.get("power")
            ),
            inline=True
        )

        embed.add_field(
            name="👥 Members",
            value=get_value(
                alliance_data,
                "count"
            ),
            inline=True
        )

        embed.add_field(
            name="👑 Leader",
            value=get_value(
                alliance_data,
                "leader_name"
            ),
            inline=True
        )

        if isinstance(
            members,
            list
        ) and members:

            members = sorted(
                members,
                key=lambda member: float(
                    member.get("power") or 0
                ),
                reverse=True
            )

            lines = []

            for index, member in enumerate(
                members[:10],
                1
            ):

                name = (
                    member.get("nick_name")
                    or member.get("name")
                    or "Unknown"
                )

                power = format_number(
                    member.get("power")
                )

                lines.append(
                    f"`{index}.` **{name}** — {power}"
                )

            if lines:

                embed.add_field(
                    name="🏆 Top 10 Members",
                    value="\n".join(lines),
                    inline=False
                )

        await interaction.followup.send(
            embed=embed
        )

    except Exception as error:

        await send_error(
            interaction,
            error
        )


# =========================================================
# KINGDOM
# =========================================================

@bot.tree.command(
    name="kingdom",
    description="Get kingdom statistics"
)
@app_commands.describe(
    kingdom_id="Kingdom ID"
)
async def kingdom(
    interaction: discord.Interaction,
    kingdom_id: int
):

    await interaction.response.defer()

    try:

        data = await api.get(
            f"/kingdoms/{kingdom_id}"
        )

        kingdom_data = data.get(
            "kingdom",
            data
        )

        embed = discord.Embed(
            title=f"🌍 Kingdom {kingdom_id}"
        )

        fields = [
            (
                "⚡ Power",
                format_number(
                    kingdom_data.get("power")
                )
            ),
            (
                "👥 Players",
                format_number(
                    kingdom_data.get("player_count")
                )
            ),
            (
                "🟢 Active 7d",
                format_number(
                    kingdom_data.get("active_7d")
                )
            ),
            (
                "🛡️ Alliances",
                format_number(
                    kingdom_data.get("alliance_count")
                )
            ),
            (
                "⚔️ Kills",
                format_number(
                    kingdom_data.get("kills")
                )
            ),
            (
                "🦸 Hero Power",
                format_number(
                    kingdom_data.get("hero_power")
                )
            ),
            (
                "🐎 Troop Power",
                format_number(
                    kingdom_data.get("troop_power")
                )
            ),
            (
                "🐾 Pet Power",
                format_number(
                    kingdom_data.get("pet_power")
                )
            )
        ]

        for name, val in fields:

            embed.add_field(
                name=name,
                value=val,
                inline=True
            )

        await interaction.followup.send(
            embed=embed
        )

    except Exception as error:

        await send_error(
            interaction,
            error
        )


# =========================================================
# RANK
# =========================================================

@bot.tree.command(
    name="rank",
    description="Show a MightPulse kingdom leaderboard"
)
@app_commands.describe(
    kingdom_id="Kingdom ID",
    board="Leaderboard name",
    limit="Number of results"
)
async def rank(
    interaction: discord.Interaction,
    kingdom_id: int,
    board: str = "personal_power",
    limit: app_commands.Range[int, 1, 25] = 10
):

    await interaction.response.defer()

    try:

        data = await api.get(
            f"/kingdoms/{kingdom_id}/ranks",
            {
                "board": board,
                "limit": limit
            }
        )

        rows = (
            data.get("leaderboard")
            or data.get("ranks")
            or data.get("items")
            or data.get("players")
            or data.get("alliances")
            or []
        )

        if not rows:

            await interaction.followup.send(
                f"ℹ️ No ranking data returned for "
                f"`{board}` in kingdom `{kingdom_id}`."
            )

            return

        lines = []

        for index, row in enumerate(
            rows[:limit],
            1
        ):

            name = (
                row.get("nick_name")
                or row.get("name")
                or row.get("abbr")
                or "Unknown"
            )

            score = row.get(
                "score"
            )

            if score is None:

                score = row.get(
                    "value"
                )

            if score is None:

                score = row.get(
                    "power"
                )

            lines.append(
                f"`{index:02}` **{name}** — "
                f"{format_number(score)}"
            )

        embed = discord.Embed(
            title=(
                f"🏆 Kingdom {kingdom_id} — "
                f"{board}"
            ),
            description="\n".join(lines)
        )

        await interaction.followup.send(
            embed=embed
        )

    except Exception as error:

        await send_error(
            interaction,
            error
        )


# =========================================================
# DISCORD COMMAND SYNC
# =========================================================

async def sync_commands():

    if DISCORD_GUILD_ID:

        guild = discord.Object(
            id=int(DISCORD_GUILD_ID)
        )

        # Copy global commands to this server
        bot.tree.copy_global_to(
            guild=guild
        )

        synced = await bot.tree.sync(
            guild=guild
        )

        log.info(
            "Synced %s commands to guild %s",
            len(synced),
            DISCORD_GUILD_ID
        )

    else:

        synced = await bot.tree.sync()

        log.info(
            "Synced %s global commands",
            len(synced)
        )


# =========================================================
# SETUP HOOK
# =========================================================

@bot.event
async def setup_hook():

    log.info(
        "Running Discord setup..."
    )

    await api.start()

    await sync_commands()

    log.info(
        "Discord setup completed."
    )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    log.info(
        "========================================"
    )

    log.info(
        "BOT ONLINE"
    )

    log.info(
        "Bot: %s",
        bot.user
    )

    log.info(
        "Application ID: %s",
        bot.application_id
    )

    log.info(
        "========================================"
    )


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

async def health(request):

    return web.json_response(
        {
            "status": "online",
            "bot": (
                str(bot.user)
                if bot.user
                else "starting"
            )
        }
    )


async def start_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health
    )

    app.router.add_get(
        "/health",
        health
    )

    runner = web.AppRunner(
        app
    )

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    log.info(
        "Health server listening on port %s",
        PORT
    )

    return runner


# =========================================================
# MAIN
# =========================================================

async def main():

    runner = await start_web_server()

    try:

        await bot.start(
            DISCORD_TOKEN
        )

    finally:

        await api.close()

        await runner.cleanup()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    asyncio.run(main())
