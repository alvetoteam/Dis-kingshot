import os
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web, ClientSession, ClientTimeout


# =========================
# CONFIG
# =========================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
MIGHTPULSE_API_KEY = os.getenv("MIGHTPULSE_API_KEY")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
PORT = int(os.getenv("PORT", "10000"))

API_BASE = "https://api.mightpulse.com/v1"

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

if not MIGHTPULSE_API_KEY:
    raise RuntimeError("MIGHTPULSE_API_KEY is missing")


# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("mightpulse")


# =========================
# DISCORD
# =========================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# MIGHTPULSE API
# =========================

class MightPulseAPI:

    def __init__(self, api_key):
        self.api_key = api_key
        self.session = None

    async def start(self):

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

    async def get(self, endpoint, params=None):

        url = f"{API_BASE}{endpoint}"

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

            if response.status == 401:
                raise Exception(
                    "MightPulse API Key غير صحيح أو غير مصرح."
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

                raise Exception(message)

            return data


api = MightPulseAPI(MIGHTPULSE_API_KEY)


# =========================
# HELPERS
# =========================

def value(data, key, default="N/A"):

    result = data.get(key)

    if result is None or result == "":
        return default

    return str(result)


def number(value):

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


async def error_message(
    interaction: discord.Interaction,
    error
):

    message = f"❌ {error}"

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


# =========================
# PLAYER
# =========================

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

        alliance = (
            player_data.get("alliance")
            or {}
        )

        embed = discord.Embed(
            title=f"👤 {value(player_data, 'nick_name')}",
            description=(
                f"Governor ID: "
                f"`{value(player_data, 'governor_id', governor_id)}`"
            )
        )

        embed.add_field(
            name="Kingdom",
            value=value(player_data, "kid"),
            inline=True
        )

        embed.add_field(
            name="Power",
            value=number(
                player_data.get("power")
            ),
            inline=True
        )

        embed.add_field(
            name="TC",
            value=value(
                player_data,
                "town_center_level"
            ),
            inline=True
        )

        embed.add_field(
            name="VIP",
            value=value(
                player_data,
                "vip"
            ),
            inline=True
        )

        embed.add_field(
            name="Kills",
            value=number(
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
            name="Alliance",
            value=str(alliance_name),
            inline=False
        )

        await interaction.followup.send(
            embed=embed
        )

    except Exception as error:

        await error_message(
            interaction,
            error
        )


# =========================
# ALLIANCE
# =========================

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
            or []
        )

        embed = discord.Embed(
            title=(
                f"🛡️ "
                f"{value(alliance_data, 'name')}"
            ),
            description=(
                f"Kingdom: `{kingdom_id}`\n"
                f"Tag: `{tag}`"
            )
        )

        embed.add_field(
            name="Power",
            value=number(
                alliance_data.get("power")
            ),
            inline=True
        )

        embed.add_field(
            name="Members",
            value=value(
                alliance_data,
                "count"
            ),
            inline=True
        )

        embed.add_field(
            name="Leader",
            value=value(
                alliance_data,
                "leader_name"
            ),
            inline=True
        )

        # Top 10 members

        members = sorted(
            members,
            key=lambda x: float(
                x.get("power") or 0
            ),
            reverse=True
        )

        top_members = members[:10]

        if top_members:

            lines = []

            for index, member in enumerate(
                top_members,
                1
            ):

                name = (
                    member.get("nick_name")
                    or member.get("name")
                    or "Unknown"
                )

                power = number(
                    member.get("power")
                )

                lines.append(
                    f"`{index}.` **{name}** — {power}"
                )

            embed.add_field(
                name="Top 10 Members",
                value="\n".join(lines),
                inline=False
            )

        await interaction.followup.send(
            embed=embed
        )

    except Exception as error:

        await error_message(
            interaction,
            error
        )


# =========================
# KINGDOM
# =========================

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
                "Power",
                number(
                    kingdom_data.get("power")
                )
            ),

            (
                "Players",
                number(
                    kingdom_data.get(
                        "player_count"
                    )
                )
            ),

            (
                "Active 7d",
                number(
                    kingdom_data.get(
                        "active_7d"
                    )
                )
            ),

            (
                "Alliances",
                number(
                    kingdom_data.get(
                        "alliance_count"
                    )
                )
            ),

            (
                "Kills",
                number(
                    kingdom_data.get("kills")
                )
            ),

            (
                "Hero Power",
                number(
                    kingdom_data.get(
                        "hero_power"
                    )
                )
            ),

            (
                "Troop Power",
                number(
                    kingdom_data.get(
                        "troop_power"
                    )
                ),

            (
                "Pet Power",
                number(
                    kingdom_data.get(
                        "pet_power"
                    )
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

        await error_message(
            interaction,
            error
        )


# =========================
# HEALTH CHECK FOR RENDER
# =========================

async def health(request):

    return web.json_response(
        {
            "status": "online",
            "bot": str(bot.user)
            if bot.user
            else "starting"
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

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    log.info(
        "Web server running on port %s",
        PORT
    )

    return runner


# =========================
# BOT EVENTS
# =========================

@bot.event
async def on_ready():

    log.info(
        "Logged in as %s",
        bot.user
    )


# =========================
# START
# =========================

async def main():

    await api.start()

    runner = await start_web_server()

    try:

        if DISCORD_GUILD_ID:

            guild = discord.Object(
                id=int(DISCORD_GUILD_ID)
            )

            bot.tree.copy_global_to(
                guild=guild
            )

            await bot.tree.sync(
                guild=guild
            )

            log.info(
                "Slash commands synced to server %s",
                DISCORD_GUILD_ID
            )

        else:

            await bot.tree.sync()

            log.info(
                "Global slash commands synced"
            )

        await bot.start(
            DISCORD_TOKEN
        )

    finally:

        await api.close()

        await runner.cleanup()


if __name__ == "__main__":

    asyncio.run(main())
