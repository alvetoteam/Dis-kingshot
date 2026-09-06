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

                raise Exception(str(message))

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


def first_value(
    data,
    keys,
    default="N/A"
):

    if not isinstance(data, dict):
        return default

    for key in keys:

        value = data.get(key)

        if value is not None and value != "":
            return value

    return default


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


def valid_url(value):

    if not isinstance(value, str):
        return None

    value = value.strip()

    if value.startswith("https://") or value.startswith("http://"):
        return value

    return None


def format_stars(value):

    if value is None:
        return "N/A"

    try:

        stars = int(value)

        if stars <= 0:
            return "0"

        return "⭐" * min(stars, 10)

    except Exception:

        return str(value)


def get_hero_list(
    player_data,
    data
):

    """
    Try several possible locations for the heroes.
    """

    heroes = (
        player_data.get("heroes")
        or data.get("heroes")
        or []
    )

    if isinstance(heroes, dict):

        # Some APIs return:
        # {"items": [...]}
        # {"heroes": [...]}

        heroes = (
            heroes.get("items")
            or heroes.get("heroes")
            or heroes.get("data")
            or []
        )

    if not isinstance(heroes, list):
        return []

    return heroes


def hero_name(hero):

    return str(
        first_value(
            hero,
            [
                "name",
                "hero_name",
                "nickname",
                "nick_name",
                "display_name"
            ],
            "Unknown Hero"
        )
    )


def hero_level(hero):

    return first_value(
        hero,
        [
            "level",
            "lv",
            "hero_level"
        ],
        "N/A"
    )


def hero_stars(hero):

    return first_value(
        hero,
        [
            "stars",
            "star",
            "star_level"
        ],
        "N/A"
    )


def hero_power(hero):

    return first_value(
        hero,
        [
            "power",
            "hero_power"
        ],
        None
    )


def get_hero_gear(hero):

    gear = (
        hero.get("gear")
        or hero.get("gears")
        or hero.get("equipment")
        or hero.get("hero_gear")
        or []
    )

    if isinstance(gear, dict):

        gear = (
            gear.get("items")
            or gear.get("gear")
            or gear.get("equipment")
            or gear.get("data")
            or []
        )

    if isinstance(gear, list):
        return gear

    return []


def format_gear(gear):

    if not isinstance(gear, dict):
        return str(gear)

    name = first_value(
        gear,
        [
            "name",
            "gear_name",
            "equipment_name",
            "display_name"
        ],
        "Gear"
    )

    level = first_value(
        gear,
        [
            "level",
            "lv",
            "gear_level"
        ],
        None
    )

    stars = first_value(
        gear,
        [
            "stars",
            "star",
            "star_level"
        ],
        None
    )

    tier = first_value(
        gear,
        [
            "tier",
            "quality",
            "rarity"
        ],
        None
    )

    parts = [f"**{name}**"]

    if level is not None:
        parts.append(f"Lv.{level}")

    if stars is not None:
        parts.append(f"⭐{stars}")

    if tier is not None:
        parts.append(f"({tier})")

    return " ".join(parts)


def get_exclusive_gear(hero):

    exclusive = (
        hero.get("exclusive_gear")
        or hero.get("exclusive")
        or hero.get("exclusiveGear")
    )

    if not exclusive:
        return None

    if isinstance(exclusive, list):

        return exclusive

    if isinstance(exclusive, dict):

        return [exclusive]

    return None


# =========================================================
# ERROR HANDLER
# =========================================================

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
# HERO VIEW
# =========================================================

class HeroView(discord.ui.View):

    def __init__(
        self,
        interaction,
        heroes,
        player_name,
        timeout=180
    ):

        super().__init__(
            timeout=timeout
        )

        self.interaction = interaction
        self.heroes = heroes
        self.player_name = player_name
        self.current = 0

        self.update_buttons()

    def update_buttons(self):

        self.previous.disabled = (
            self.current <= 0
        )

        self.next.disabled = (
            self.current >= len(self.heroes) - 1
        )

    def create_embed(self):

        hero = self.heroes[self.current]

        name = hero_name(hero)

        level = hero_level(hero)

        stars = hero_stars(hero)

        power = hero_power(hero)

        embed = discord.Embed(
            title=f"🦸 {name}",
            description=(
                f"**Player:** {self.player_name}\n"
                f"**Hero:** {self.current + 1}/{len(self.heroes)}"
            )
        )

        embed.add_field(
            name="📊 Level",
            value=str(level),
            inline=True
        )

        embed.add_field(
            name="⭐ Stars",
            value=format_stars(stars),
            inline=True
        )

        if power is not None:

            embed.add_field(
                name="⚡ Power",
                value=format_number(power),
                inline=True
            )

        # -------------------------------------------------
        # HERO GEAR
        # -------------------------------------------------

        gear = get_hero_gear(hero)

        if gear:

            gear_lines = []

            for item in gear[:6]:

                gear_lines.append(
                    format_gear(item)
                )

            embed.add_field(
                name="🛡️ Gear",
                value="\n".join(gear_lines),
                inline=False
            )

        else:

            embed.add_field(
                name="🛡️ Gear",
                value="N/A",
                inline=False
            )

        # -------------------------------------------------
        # EXCLUSIVE GEAR
        # -------------------------------------------------

        exclusive = get_exclusive_gear(hero)

        if exclusive:

            exclusive_lines = []

            for item in exclusive[:4]:

                if isinstance(item, dict):

                    exclusive_lines.append(
                        format_gear(item)
                    )

                else:

                    exclusive_lines.append(
                        str(item)
                    )

            embed.add_field(
                name="💠 Exclusive Gear",
                value="\n".join(exclusive_lines),
                inline=False
            )

        # -------------------------------------------------
        # ENHANCEMENT
        # -------------------------------------------------

        enhancement = first_value(
            hero,
            [
                "enhancement",
                "enhance",
                "enhancement_level"
            ],
            None
        )

        if enhancement is not None:

            embed.add_field(
                name="🔨 Enhancement",
                value=str(enhancement),
                inline=True
            )

        # -------------------------------------------------
        # REFINE
        # -------------------------------------------------

        refine = first_value(
            hero,
            [
                "refine",
                "refinement",
                "refine_level"
            ],
            None
        )

        if refine is not None:

            embed.add_field(
                name="💎 Refine",
                value=str(refine),
                inline=True
            )

        embed.set_footer(
            text="Data provided by MightPulse"
        )

        return embed

    @discord.ui.button(
        label="Previous",
        emoji="◀️",
        style=discord.ButtonStyle.secondary
    )
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if interaction.user.id != self.interaction.user.id:

            await interaction.response.send_message(
                "❌ هذه الصفحة ليست لك.",
                ephemeral=True
            )

            return

        if self.current > 0:

            self.current -= 1

        self.update_buttons()

        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self
        )

    @discord.ui.button(
        label="Next",
        emoji="▶️",
        style=discord.ButtonStyle.primary
    )
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if interaction.user.id != self.interaction.user.id:

            await interaction.response.send_message(
                "❌ هذه الصفحة ليست لك.",
                ephemeral=True
            )

            return

        if self.current < len(self.heroes) - 1:

            self.current += 1

        self.update_buttons()

        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self
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

        governor_id = governor_id.strip()

        if not governor_id:
            raise Exception(
                "Please enter a valid Governor ID."
            )

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

        # -------------------------------------------------
        # BASIC DATA
        # -------------------------------------------------

        alliance = (
            player_data.get("alliance")
            or {}
        )

        if not isinstance(
            alliance,
            dict
        ):
            alliance = {}

        player_name = (
            player_data.get("nick_name")
            or player_data.get("name")
            or player_data.get("nickname")
            or "Unknown Player"
        )

        governor_value = (
            player_data.get("governor_id")
            or player_data.get("id")
            or governor_id
        )

        embed = discord.Embed(
            title=f"👤 {player_name}",
            description=(
                "Governor ID: "
                f"`{governor_value}`"
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
            or alliance.get("tag")
            or "No Alliance"
        )

        embed.add_field(
            name="🛡️ Alliance",
            value=str(alliance_name),
            inline=False
        )

        # -------------------------------------------------
        # AVATAR
        # -------------------------------------------------

        avatar = valid_url(
            player_data.get("avatar_url")
        )

        if avatar:

            embed.set_thumbnail(
                url=avatar
            )

        # -------------------------------------------------
        # HERO BUTTON
        # -------------------------------------------------

        heroes = get_hero_list(
            player_data,
            data
        )

        embed.set_footer(
            text=(
                "Data provided by MightPulse"
                + (
                    f" • {len(heroes)} Heroes"
                    if heroes
                    else ""
                )
            )
        )

        # -------------------------------------------------
        # SEND PLAYER
        # -------------------------------------------------

        await interaction.followup.send(
            embed=embed
        )

        # -------------------------------------------------
        # SEND HERO PAGES
        # -------------------------------------------------

        if heroes:

            hero_view = HeroView(
                interaction=interaction,
                heroes=heroes,
                player_name=str(player_name)
            )

            await interaction.followup.send(
                embed=hero_view.create_embed(),
                view=hero_view
            )

    except Exception as error:

        log.exception(
            "Player command failed"
        )

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

        if not isinstance(
            alliance_data,
            dict
        ):

            raise Exception(
                "MightPulse returned an unexpected alliance response."
            )

        members = (
            data.get("members")
            or data.get("roster")
            or alliance_data.get("members")
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
                )
                if isinstance(member, dict)
                else 0,
                reverse=True
            )

            lines = []

            for index, member in enumerate(
                members[:10],
                1
            ):

                if not isinstance(
                    member,
                    dict
                ):
                    continue

                name = (
                    member.get("nick_name")
                    or member.get("name")
                    or member.get("nickname")
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

        embed.set_footer(
            text="Data provided by MightPulse"
        )

        await interaction.followup.send(
            embed=embed
        )

    except Exception as error:

        log.exception(
            "Alliance command failed"
        )

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

        if not isinstance(
            kingdom_data,
            dict
        ):

            raise Exception(
                "MightPulse returned an unexpected kingdom response."
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

        embed.set_footer(
            text="Data provided by MightPulse"
        )

        await interaction.followup.send(
            embed=embed
        )

    except Exception as error:

        log.exception(
            "Kingdom command failed"
        )

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

            if not isinstance(
                row,
                dict
            ):
                continue

            name = (
                row.get("nick_name")
                or row.get("name")
                or row.get("abbr")
                or row.get("nickname")
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

        if not lines:

            raise Exception(
                "No valid ranking entries returned."
            )

        embed = discord.Embed(
            title=(
                f"🏆 Kingdom {kingdom_id} — "
                f"{board}"
            ),
            description="\n".join(lines)
        )

        embed.set_footer(
            text="Data provided by MightPulse"
        )

        await interaction.followup.send(
            embed=embed
        )

    except Exception as error:

        log.exception(
            "Rank command failed"
        )

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
