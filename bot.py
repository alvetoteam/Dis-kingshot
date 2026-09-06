import os
import asyncio
import logging

import aiohttp
from aiohttp import web

import discord
from discord import app_commands
from discord.ext import commands


# =========================================================
# CONFIG
# =========================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")

MIGHTPULSE_API_KEY = os.getenv("MIGHTPULSE_API_KEY")

PORT = int(os.getenv("PORT", "10000"))

MIGHTPULSE_BASE_URL = "https://api.mightpulse.com/v1"


# =========================================================
# VALIDATION
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
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("KingshotBot")


# =========================================================
# HELPERS
# =========================================================

def first_value(*values, default=None):
    for value in values:
        if value is not None and value != "":
            return value
    return default


def format_number(value):
    if value is None:
        return "N/A"

    try:
        number = float(value)

        if number.is_integer():
            return f"{int(number):,}"

        return f"{number:,.2f}"

    except (ValueError, TypeError):
        return str(value)


def to_number(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def valid_url(value):
    if not isinstance(value, str):
        return None

    value = value.strip()

    if value.startswith("http://") or value.startswith("https://"):
        return value

    return None


def player_from_response(data):
    player = data.get("player")

    if isinstance(player, dict):
        return player

    return {}


def heroes_from_response(data):
    heroes = data.get("heroes")

    if isinstance(heroes, list):
        return heroes

    return []


def alliance_name(player):
    alliance = player.get("alliance")

    if isinstance(alliance, dict):
        return first_value(
            alliance.get("name"),
            alliance.get("abbr"),
            default="No Alliance"
        )

    if isinstance(alliance, str):
        return alliance

    return "No Alliance"


# =========================================================
# HERO HELPERS
# =========================================================

def hero_power(hero):
    return to_number(hero.get("power"))


def total_hero_power(heroes):
    return sum(
        hero_power(hero)
        for hero in heroes
    )


def strongest_hero(heroes):
    if not heroes:
        return None

    return max(
        heroes,
        key=hero_power
    )


def hero_stars(hero):
    value = first_value(
        hero.get("stars"),
        hero.get("star"),
        default=0
    )

    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def star_text(hero):
    stars = hero_stars(hero)

    if stars <= 0:
        return "N/A"

    return "⭐" * stars


def format_hero_gear(hero):
    gear = hero.get("gear")

    if not isinstance(gear, list) or not gear:
        return "No gear"

    lines = []

    for item in gear:
        if not isinstance(item, dict):
            continue

        slot = first_value(
            item.get("slot"),
            default="Gear"
        )

        name = first_value(
            item.get("name"),
            default=""
        )

        enhancement = first_value(
            item.get("enhancement_level"),
            default=0
        )

        refine = first_value(
            item.get("refine_level"),
            default=0
        )

        quality = first_value(
            item.get("quality_label"),
            item.get("quality"),
            default=""
        )

        text = (
            f"**{slot}**"
            + (f" — {name}" if name else "")
            + f" | +{enhancement}"
            + f" | Refine {refine}"
        )

        if quality:
            text += f" | {quality}"

        if item.get("red"):
            text += " 🔴"

        lines.append(text)

    return "\n".join(lines) or "No gear"


def format_exclusive_gear(hero):
    gear = hero.get("exclusive_gear")

    if not isinstance(gear, dict):
        return "No Exclusive Gear"

    name = first_value(
        gear.get("name"),
        default="Exclusive Gear"
    )

    level = first_value(
        gear.get("level"),
        default=0
    )

    return (
        f"**{name}**\n"
        f"Level: **{level}**"
    )


def format_skills(hero):
    skills = hero.get("skill_levels")

    if not isinstance(skills, list) or not skills:
        return "N/A"

    lines = []

    for skill in skills:
        if not isinstance(skill, dict):
            continue

        skill_id = first_value(
            skill.get("id"),
            default="?"
        )

        level = first_value(
            skill.get("level"),
            default="?"
        )

        lines.append(
            f"Skill {skill_id}: **Lv.{level}**"
        )

    return "\n".join(lines) or "N/A"


# =========================================================
# GOVERNOR GEAR HELPERS
# =========================================================

def gov_gear_from_response(data):
    gear = data.get("gov_gear")

    if isinstance(gear, dict):
        return gear

    return {}


def gov_gear_items(data):
    gear = gov_gear_from_response(data)

    items = gear.get("items")

    if isinstance(items, list):
        return items

    return []


def gov_gear_score(data):
    total = 0

    for item in gov_gear_items(data):
        if isinstance(item, dict):
            total += to_number(
                item.get("score")
            )

    return total


def gov_gear_combat(data):
    total = 0

    for item in gov_gear_items(data):
        if isinstance(item, dict):
            total += to_number(
                item.get("combat")
            )

    return total


def gov_gear_gems(data):
    total = 0

    for item in gov_gear_items(data):
        if not isinstance(item, dict):
            continue

        gems = item.get("gems")

        if isinstance(gems, list):
            total += len(gems)

    return total


def gov_gear_by_slot(data):
    result = {}

    for item in gov_gear_items(data):

        if not isinstance(item, dict):
            continue

        slot = first_value(
            item.get("slot"),
            default="Unknown"
        )

        result[str(slot)] = item

    return result


def gov_gear_item_text(item):
    if not isinstance(item, dict):
        return "N/A"

    name = first_value(
        item.get("name"),
        default="Governor Gear"
    )

    quality = first_value(
        item.get("quality"),
        default="N/A"
    )

    tier = first_value(
        item.get("tier"),
        default="N/A"
    )

    star = first_value(
        item.get("star"),
        default="N/A"
    )

    strength = first_value(
        item.get("strength_level"),
        default="N/A"
    )

    score = item.get("score")
    combat = item.get("combat")

    gems = item.get("gems")

    if not isinstance(gems, list):
        gems = []

    return (
        f"**{name}**\n"
        f"Quality: **{quality}**\n"
        f"Tier: **{tier}** | ⭐ **{star}**\n"
        f"Strength: **{strength}**\n"
        f"Score: **{format_number(score)}**\n"
        f"Combat: **{format_number(combat)}**\n"
        f"💎 Gems: **{len(gems)}**"
    )


# =========================================================
# MIGHTPULSE API
# =========================================================

class MightPulseAPI:

    def __init__(self, api_key):
        self.api_key = api_key
        self.session = None

    async def start(self):

        if self.session is None or self.session.closed:

            timeout = aiohttp.ClientTimeout(
                total=100
            )

            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "X-Api-Key": self.api_key,
                    "Accept": "application/json",
                    "User-Agent": "KingshotDiscordBot/1.0"
                }
            )

    async def close(self):

        if self.session and not self.session.closed:
            await self.session.close()

    async def get(self, endpoint, params=None):

        await self.start()

        url = f"{MIGHTPULSE_BASE_URL}{endpoint}"

        logger.info(
            "MightPulse GET %s %s",
            endpoint,
            params or {}
        )

        try:

            async with self.session.get(
                url,
                params=params
            ) as response:

                text = await response.text()

                if response.status == 200:

                    try:
                        return await response.json()

                    except Exception:

                        return {
                            "ok": False,
                            "error": "Invalid JSON",
                            "message": text[:500]
                        }

                if response.status == 401:

                    return {
                        "ok": False,
                        "error": "401 Unauthorized",
                        "message": text[:500]
                    }

                if response.status == 403:

                    return {
                        "ok": False,
                        "error": "403 Forbidden",
                        "message": text[:500]
                    }

                if response.status == 404:

                    return {
                        "ok": False,
                        "error": "404 Not Found",
                        "message": text[:500]
                    }

                if response.status == 429:

                    return {
                        "ok": False,
                        "error": "429 Rate Limited",
                        "message": text[:500]
                    }

                return {
                    "ok": False,
                    "error": f"HTTP {response.status}",
                    "message": text[:500]
                }

        except asyncio.TimeoutError:

            return {
                "ok": False,
                "error": "Timeout",
                "message": "MightPulse request timed out."
            }

        except aiohttp.ClientError as e:

            return {
                "ok": False,
                "error": "Connection Error",
                "message": str(e)
            }

        except Exception as e:

            logger.exception(
                "Unexpected API error"
            )

            return {
                "ok": False,
                "error": "Unknown Error",
                "message": str(e)
            }

    async def get_player(self, governor_id):

        return await self.get(
            f"/players/{governor_id}",
            params={
                "include": "base,heroes,ranks,gov_gear"
            }
        )

    async def get_alliance(self, kid, tag):

        return await self.get(
            f"/alliances/{kid}/{tag}",
            params={
                "include": "info,roster"
            }
        )

    async def get_kingdom(self, kid):

        return await self.get(
            f"/kingdoms/{kid}"
        )

    async def get_kingdom_ranks(
        self,
        kid,
        board="personal_power",
        limit=100
    ):

        return await self.get(
            f"/kingdoms/{kid}/ranks",
            params={
                "board": board,
                "limit": limit
            }
        )


api = MightPulseAPI(
    MIGHTPULSE_API_KEY
)


# =========================================================
# DISCORD
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    application_id=int(
        DISCORD_APPLICATION_ID
    )
)


# =========================================================
# HERO PAGINATION
# =========================================================

class HeroView(discord.ui.View):

    def __init__(
        self,
        heroes,
        player,
        timeout=300
    ):
        super().__init__(
            timeout=timeout
        )

        self.heroes = heroes
        self.player = player
        self.index = 0

        self.update_buttons()

    def update_buttons(self):

        self.previous_button.disabled = (
            self.index <= 0
        )

        self.next_button.disabled = (
            self.index >= len(self.heroes) - 1
        )

    def create_embed(self):

        hero = self.heroes[self.index]

        name = first_value(
            hero.get("name"),
            default="Unknown Hero"
        )

        level = first_value(
            hero.get("level"),
            default="N/A"
        )

        power = hero.get("power")

        quality = first_value(
            hero.get("quality"),
            default="N/A"
        )

        position = first_value(
            hero.get("position"),
            default="N/A"
        )

        embed = discord.Embed(
            title=f"🦸 {name}",
            description=(
                f"Hero **{self.index + 1}/{len(self.heroes)}**"
            ),
            color=discord.Color.blue()
        )

        embed.add_field(
            name="📊 Hero Stats",
            value=(
                f"Level: **{level}**\n"
                f"Stars: {star_text(hero)}\n"
                f"Power: **{format_number(power)}**\n"
                f"Quality: **{quality}**\n"
                f"Position: **{position}**"
            ),
            inline=False
        )

        gear_text = format_hero_gear(hero)

        embed.add_field(
            name="⚔️ Hero Gear",
            value=gear_text[:1024],
            inline=False
        )

        exclusive = format_exclusive_gear(hero)

        embed.add_field(
            name="🔱 Exclusive Gear",
            value=exclusive[:1024],
            inline=False
        )

        skills = format_skills(hero)

        embed.add_field(
            name="✨ Skills",
            value=skills[:1024],
            inline=False
        )

        icon = valid_url(
            hero.get("icon")
        )

        if icon:
            embed.set_thumbnail(
                url=icon
            )

        return embed

    async def refresh(self, interaction):

        self.update_buttons()

        await interaction.response.edit_message(
            embed=self.create_embed(),
            view=self
        )

    @discord.ui.button(
        label="Previous",
        emoji="⬅️",
        style=discord.ButtonStyle.secondary
    )
    async def previous_button(
        self,
        interaction,
        button
    ):

        if self.index > 0:
            self.index -= 1

        await self.refresh(
            interaction
        )

    @discord.ui.button(
        label="Next",
        emoji="➡️",
        style=discord.ButtonStyle.primary
    )
    async def next_button(
        self,
        interaction,
        button
    ):

        if self.index < len(self.heroes) - 1:
            self.index += 1

        await self.refresh(
            interaction
        )


# =========================================================
# BOT READY
# =========================================================

@bot.event
async def on_ready():

    logger.info(
        "Logged in as %s (%s)",
        bot.user,
        bot.user.id
    )

    try:

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

            logger.info(
                "Synced %d commands to guild %s",
                len(synced),
                DISCORD_GUILD_ID
            )

        else:

            synced = await bot.tree.sync()

            logger.info(
                "Synced %d global commands",
                len(synced)
            )

    except Exception:

        logger.exception(
            "Command sync failed"
        )


# =========================================================
# /PLAYER
# =========================================================

@bot.tree.command(
    name="player",
    description="Show Kingshot player information"
)
@app_commands.describe(
    governor_id="Governor ID"
)
async def player_command(
    interaction: discord.Interaction,
    governor_id: str
):

    await interaction.response.defer()

    data = await api.get_player(
        governor_id
    )

    if not data.get("ok", True):

        await interaction.followup.send(
            f"❌ **{data.get('error')}**\n"
            f"{data.get('message', '')}"
        )

        return

    player = player_from_response(
        data
    )

    heroes = heroes_from_response(
        data
    )

    name = first_value(
        player.get("nick_name"),
        default="Unknown"
    )

    embed = discord.Embed(
        title=f"👤 {name}",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="🆔 Governor ID",
        value=f"`{governor_id}`",
        inline=True
    )

    embed.add_field(
        name="🌍 Kingdom",
        value=f"**{player.get('kid', 'N/A')}**",
        inline=True
    )

    embed.add_field(
        name="⚡ Power",
        value=f"**{format_number(player.get('power'))}**",
        inline=True
    )

    embed.add_field(
        name="☠️ Kills",
        value=f"**{format_number(player.get('kills'))}**",
        inline=True
    )

    embed.add_field(
        name="🏰 Town Center",
        value=f"**{player.get('town_center_level', 'N/A')}**",
        inline=True
    )

    embed.add_field(
        name="👑 VIP",
        value=f"**{player.get('vip', 'N/A')}**",
        inline=True
    )

    embed.add_field(
        name="🤝 Alliance",
        value=f"**{alliance_name(player)}**",
        inline=True
    )

    avatar = valid_url(
        player.get("avatar_url")
    )

    if avatar:
        embed.set_thumbnail(
            url=avatar
        )

    await interaction.followup.send(
        embed=embed
    )

    # -----------------------------------------------------
    # HERO SUMMARY
    # -----------------------------------------------------

    if heroes:

        best = strongest_hero(
            heroes
        )

        hero_summary = (
            f"Total Heroes: **{len(heroes)}**\n"
            f"Total Hero Power: **"
            f"{format_number(total_hero_power(heroes))}"
            f"**"
        )

        if best:

            hero_summary += (
                f"\n\n🏆 Strongest Hero: "
                f"**{best.get('name', 'Unknown')}**\n"
                f"Power: **{format_number(best.get('power'))}**"
            )

        hero_embed = discord.Embed(
            title="🦸 Heroes",
            description=hero_summary,
            color=discord.Color.purple()
        )

        await interaction.followup.send(
            embed=hero_embed,
            view=HeroView(
                heroes,
                player
            )
        )

    # -----------------------------------------------------
    # GOVERNOR GEAR
    # -----------------------------------------------------

    gov = gov_gear_from_response(
        data
    )

    gov_embed = discord.Embed(
        title="👑 Governor Gear",
        color=discord.Color.gold()
    )

    if not gov:

        gov_embed.description = (
            "No Governor Gear section was returned."
        )

    elif gov.get("hidden"):

        gov_embed.description = (
            gov.get("message")
            or "Governor Gear is hidden."
        )

    else:

        items = gov_gear_items(
            data
        )

        if not items:

            gov_embed.description = (
                "No Governor Gear items found."
            )

        else:

            gov_embed.description = (
                f"Total Score: **"
                f"{format_number(gov_gear_score(data))}"
                f"**\n"
                f"Total Combat: **"
                f"{format_number(gov_gear_combat(data))}"
                f"**\n"
                f"💎 Gems: **{gov_gear_gems(data)}**"
            )

            for item in items:

                slot = first_value(
                    item.get("slot"),
                    item.get("name"),
                    default="Gear"
                )

                gov_embed.add_field(
                    name=f"🛡️ {slot}",
                    value=gov_gear_item_text(item),
                    inline=True
                )

    await interaction.followup.send(
        embed=gov_embed
    )


# =========================================================
# /COMPARE
# =========================================================

@bot.tree.command(
    name="compare",
    description="Compare two Kingshot players"
)
@app_commands.describe(
    governor_id_1="First Governor ID",
    governor_id_2="Second Governor ID"
)
async def compare_command(
    interaction: discord.Interaction,
    governor_id_1: str,
    governor_id_2: str
):

    await interaction.response.defer()

    data1, data2 = await asyncio.gather(
        api.get_player(governor_id_1),
        api.get_player(governor_id_2)
    )

    if not data1.get("ok", True):

        await interaction.followup.send(
            f"❌ Player 1:\n"
            f"{data1.get('error')}\n"
            f"{data1.get('message', '')}"
        )

        return

    if not data2.get("ok", True):

        await interaction.followup.send(
            f"❌ Player 2:\n"
            f"{data2.get('error')}\n"
            f"{data2.get('message', '')}"
        )

        return

    p1 = player_from_response(
        data1
    )

    p2 = player_from_response(
        data2
    )

    h1 = heroes_from_response(
        data1
    )

    h2 = heroes_from_response(
        data2
    )

    name1 = first_value(
        p1.get("nick_name"),
        default=governor_id_1
    )

    name2 = first_value(
        p2.get("nick_name"),
        default=governor_id_2
    )

    # =====================================================
    # VALUES
    # =====================================================

    power1 = p1.get("power")
    power2 = p2.get("power")

    kills1 = p1.get("kills")
    kills2 = p2.get("kills")

    tc1 = p1.get("town_center_level")
    tc2 = p2.get("town_center_level")

    vip1 = p1.get("vip")
    vip2 = p2.get("vip")

    hero_power1 = total_hero_power(h1)
    hero_power2 = total_hero_power(h2)

    hero_count1 = len(h1)
    hero_count2 = len(h2)

    gear_score1 = gov_gear_score(
        data1
    )

    gear_score2 = gov_gear_score(
        data2
    )

    gear_combat1 = gov_gear_combat(
        data1
    )

    gear_combat2 = gov_gear_combat(
        data2
    )

    gems1 = gov_gear_gems(
        data1
    )

    gems2 = gov_gear_gems(
        data2
    )

    # =====================================================
    # MAIN EMBED
    # =====================================================

    embed = discord.Embed(
        title="⚔️ Player Comparison",
        color=discord.Color.gold()
    )

    embed.description = (
        f"**{name1}**  `vs`  **{name2}**"
    )

    # -----------------------------------------------------
    # IDs
    # -----------------------------------------------------

    embed.add_field(
        name="🆔 Governor IDs",
        value=(
            f"**{name1}**\n"
            f"`{governor_id_1}`\n\n"
            f"**{name2}**\n"
            f"`{governor_id_2}`"
        ),
        inline=False
    )

    # -----------------------------------------------------
    # BASIC STATS
    # -----------------------------------------------------

    embed.add_field(
        name="⚡ Power",
        value=(
            f"**{name1}:**\n"
            f"{format_number(power1)}\n\n"
            f"**{name2}:**\n"
            f"{format_number(power2)}"
        ),
        inline=True
    )

    embed.add_field(
        name="☠️ Kills",
        value=(
            f"**{name1}:**\n"
            f"{format_number(kills1)}\n\n"
            f"**{name2}:**\n"
            f"{format_number(kills2)}"
        ),
        inline=True
    )

    embed.add_field(
        name="🏰 Town Center",
        value=(
            f"**{name1}:** {tc1 if tc1 is not None else 'N/A'}\n"
            f"**{name2}:** {tc2 if tc2 is not None else 'N/A'}"
        ),
        inline=True
    )

    embed.add_field(
        name="👑 VIP",
        value=(
            f"**{name1}:** {vip1 if vip1 is not None else 'N/A'}\n"
            f"**{name2}:** {vip2 if vip2 is not None else 'N/A'}"
        ),
        inline=True
    )

    # -----------------------------------------------------
    # HEROES
    # -----------------------------------------------------

    embed.add_field(
        name="🦸 Hero Power",
        value=(
            f"**{name1}:**\n"
            f"{format_number(hero_power1)}\n\n"
            f"**{name2}:**\n"
            f"{format_number(hero_power2)}"
        ),
        inline=True
    )

    embed.add_field(
        name="🦸 Hero Count",
        value=(
            f"**{name1}:** {hero_count1}\n"
            f"**{name2}:** {hero_count2}"
        ),
        inline=True
    )

    # -----------------------------------------------------
    # STRONGEST HERO
    # -----------------------------------------------------

    best1 = strongest_hero(h1)
    best2 = strongest_hero(h2)

    best1_name = (
        best1.get("name", "N/A")
        if best1
        else "N/A"
    )

    best2_name = (
        best2.get("name", "N/A")
        if best2
        else "N/A"
    )

    best1_power = (
        best1.get("power")
        if best1
        else None
    )

    best2_power = (
        best2.get("power")
        if best2
        else None
    )

    embed.add_field(
        name="🏆 Strongest Hero",
        value=(
            f"**{name1}:**\n"
            f"{best1_name}\n"
            f"Power: **{format_number(best1_power)}**\n\n"
            f"**{name2}:**\n"
            f"{best2_name}\n"
            f"Power: **{format_number(best2_power)}**"
        ),
        inline=False
    )

    # -----------------------------------------------------
    # ALLIANCE
    # -----------------------------------------------------

    embed.add_field(
        name="🤝 Alliance",
        value=(
            f"**{name1}:**\n"
            f"{alliance_name(p1)}\n\n"
            f"**{name2}:**\n"
            f"{alliance_name(p2)}"
        ),
        inline=False
    )

    # =====================================================
    # GOVERNOR GEAR SUMMARY
    # =====================================================

    gear1 = gov_gear_from_response(
        data1
    )

    gear2 = gov_gear_from_response(
        data2
    )

    if gear1.get("hidden"):

        gear1_text = (
            gear1.get("message")
            or "Hidden"
        )

    else:

        gear1_text = (
            f"Score: **{format_number(gear_score1)}**\n"
            f"Combat: **{format_number(gear_combat1)}**\n"
            f"💎 Gems: **{gems1}**"
        )

    if gear2.get("hidden"):

        gear2_text = (
            gear2.get("message")
            or "Hidden"
        )

    else:

        gear2_text = (
            f"Score: **{format_number(gear_score2)}**\n"
            f"Combat: **{format_number(gear_combat2)}**\n"
            f"💎 Gems: **{gems2}**"
        )

    embed.add_field(
        name="👑 Governor Gear",
        value=(
            f"**{name1}**\n"
            f"{gear1_text}\n\n"
            f"**{name2}**\n"
            f"{gear2_text}"
        ),
        inline=False
    )

    await interaction.followup.send(
        embed=embed
    )

    # =====================================================
    # GOVERNOR GEAR BY SLOT
    # =====================================================

    slots1 = gov_gear_by_slot(
        data1
    )

    slots2 = gov_gear_by_slot(
        data2
    )

    all_slots = list(
        dict.fromkeys(
            list(slots1.keys()) +
            list(slots2.keys())
        )
    )

    if all_slots:

        gear_embed = discord.Embed(
            title="🛡️ Governor Gear — Slot Comparison",
            description=(
                f"**{name1}** vs **{name2}**"
            ),
            color=discord.Color.orange()
        )

        for slot in all_slots:

            item1 = slots1.get(slot)
            item2 = slots2.get(slot)

            if item1:

                text1 = (
                    f"Score: **"
                    f"{format_number(item1.get('score'))}"
                    f"**\n"
                    f"Combat: **"
                    f"{format_number(item1.get('combat'))}"
                    f"**\n"
                    f"Tier: **{item1.get('tier', 'N/A')}** | "
                    f"⭐ **{item1.get('star', 'N/A')}**\n"
                    f"Strength: **"
                    f"{item1.get('strength_level', 'N/A')}"
                    f"**"
                )

            else:

                text1 = "No Gear"

            if item2:

                text2 = (
                    f"Score: **"
                    f"{format_number(item2.get('score'))}"
                    f"**\n"
                    f"Combat: **"
                    f"{format_number(item2.get('combat'))}"
                    f"**\n"
                    f"Tier: **{item2.get('tier', 'N/A')}** | "
                    f"⭐ **{item2.get('star', 'N/A')}**\n"
                    f"Strength: **"
                    f"{item2.get('strength_level', 'N/A')}"
                    f"**"
                )

            else:

                text2 = "No Gear"

            gear_embed.add_field(
                name=f"🛡️ {slot}",
                value=(
                    f"**{name1}**\n"
                    f"{text1}\n\n"
                    f"**{name2}**\n"
                    f"{text2}"
                ),
                inline=False
            )

        await interaction.followup.send(
            embed=gear_embed
        )


# =========================================================
# /ALLIANCE
# =========================================================

@bot.tree.command(
    name="alliance",
    description="Show Kingshot alliance information"
)
@app_commands.describe(
    kid="Kingdom ID",
    tag="Alliance tag"
)
async def alliance_command(
    interaction: discord.Interaction,
    kid: str,
    tag: str
):

    await interaction.response.defer()

    data = await api.get_alliance(
        kid,
        tag
    )

    if not data.get("ok", True):

        await interaction.followup.send(
            f"❌ **{data.get('error')}**\n"
            f"{data.get('message', '')}"
        )

        return

    info = data.get("info")

    if not isinstance(info, dict):

        info = data.get("alliance")

    if not isinstance(info, dict):

        info = {}

    name = first_value(
        info.get("name"),
        default=tag
    )

    embed = discord.Embed(
        title=f"🤝 {name}",
        color=discord.Color.green()
    )

    embed.add_field(
        name="🏷️ Tag",
        value=f"**{info.get('abbr', tag)}**",
        inline=True
    )

    embed.add_field(
        name="🌍 Kingdom",
        value=f"**{kid}**",
        inline=True
    )

    embed.add_field(
        name="⚡ Power",
        value=f"**{format_number(info.get('power'))}**",
        inline=True
    )

    embed.add_field(
        name="👥 Members",
        value=f"**{info.get('count', 'N/A')}**",
        inline=True
    )

    embed.add_field(
        name="👑 Leader",
        value=f"**{info.get('leader_name', 'N/A')}**",
        inline=True
    )

    embed.add_field(
        name="🏆 Power Rank",
        value=f"**{info.get('power_rank', 'N/A')}**",
        inline=True
    )

    flag = valid_url(
        info.get("flag_url")
    )

    if flag:
        embed.set_thumbnail(
            url=flag
        )

    await interaction.followup.send(
        embed=embed
    )

    members = data.get("members")

    if not isinstance(members, list):
        members = data.get("roster")

    if isinstance(members, list) and members:

        members = sorted(
            members,
            key=lambda x: to_number(
                x.get("power")
            ),
            reverse=True
        )

        lines = []

        for i, member in enumerate(
            members[:25],
            1
        ):

            nickname = first_value(
                member.get("nick_name"),
                default="Unknown"
            )

            lines.append(
                f"**{i}. {nickname}** — "
                f"{format_number(member.get('power'))} "
                f"| TC {member.get('town_center_level', 'N/A')}"
            )

        roster = discord.Embed(
            title="👥 Alliance Roster",
            description="\n".join(lines),
            color=discord.Color.green()
        )

        await interaction.followup.send(
            embed=roster
        )


# =========================================================
# /KINGDOM
# =========================================================

@bot.tree.command(
    name="kingdom",
    description="Show Kingshot kingdom information"
)
@app_commands.describe(
    kid="Kingdom ID"
)
async def kingdom_command(
    interaction: discord.Interaction,
    kid: str
):

    await interaction.response.defer()

    data = await api.get_kingdom(
        kid
    )

    if not data.get("ok", True):

        await interaction.followup.send(
            f"❌ **{data.get('error')}**\n"
            f"{data.get('message', '')}"
        )

        return

    kingdom = data.get("kingdom")

    if not isinstance(kingdom, dict):
        kingdom = data

    embed = discord.Embed(
        title=f"🌍 {kingdom.get('name', f'Kingdom {kid}')}",
        description=f"Kingdom **{kid}**",
        color=discord.Color.blue()
    )

    fields = [
        ("⚡ Power", kingdom.get("power")),
        ("👥 Players", kingdom.get("player_count")),
        ("🤝 Alliances", kingdom.get("alliance_count")),
        ("📈 Average Power", kingdom.get("avg_power")),
        ("🏆 Power Rank", kingdom.get("power_rank")),
        ("🔥 Activity Rank", kingdom.get("activity_rank")),
        ("❤️ Health", kingdom.get("health")),
        ("☠️ Kills", kingdom.get("kills")),
        ("🦸 Hero Power", kingdom.get("hero_power")),
        ("⚔️ Troop Power", kingdom.get("troop_power")),
        ("🏗️ Building Power", kingdom.get("building_power")),
        ("🔬 Research Power", kingdom.get("research_power")),
        ("👑 Governor Gear", kingdom.get("governor_gear_power")),
        ("💎 Governor Charm", kingdom.get("governor_charm_power")),
        ("🐾 Pet Power", kingdom.get("pet_power")),
        ("🧪 Mystic Trial", kingdom.get("mystic_trial")),
        ("🏝️ Island Prosperity", kingdom.get("island_prosperity")),
        ("🧠 Master Power", kingdom.get("master_power")),
    ]

    for field_name, value in fields:

        if value is None:
            continue

        embed.add_field(
            name=field_name,
            value=f"**{format_number(value)}**",
            inline=True
        )

    banner = valid_url(
        kingdom.get("banner_url")
    )

    if banner:
        embed.set_thumbnail(
            url=banner
        )

    await interaction.followup.send(
        embed=embed
    )


# =========================================================
# /RANK
# =========================================================

@bot.tree.command(
    name="rank",
    description="Show kingdom leaderboard"
)
@app_commands.describe(
    kid="Kingdom ID",
    board="Leaderboard"
)
async def rank_command(
    interaction: discord.Interaction,
    kid: str,
    board: str = "personal_power"
):

    await interaction.response.defer()

    data = await api.get_kingdom_ranks(
        kid,
        board=board,
        limit=100
    )

    if not data.get("ok", True):

        await interaction.followup.send(
            f"❌ **{data.get('error')}**\n"
            f"{data.get('message', '')}"
        )

        return

    selected = None

    # Official API can return board data in different wrappers.
    if isinstance(data.get("items"), list):
        selected = data["items"]

    elif isinstance(data.get("rankings"), list):
        selected = data["rankings"]

    elif isinstance(data.get("leaderboards"), list):
        selected = data["leaderboards"]

    elif isinstance(data.get("leaderboards"), dict):

        selected = data["leaderboards"].get(
            board
        )

        if isinstance(selected, dict):
            selected = (
                selected.get("items")
                or selected.get("entries")
            )

    if not isinstance(selected, list):

        await interaction.followup.send(
            "❌ No ranking data found."
        )

        return

    lines = []

    for index, item in enumerate(
        selected[:25],
        1
    ):

        if not isinstance(item, dict):
            continue

        name = first_value(
            item.get("nick_name"),
            item.get("name"),
            default="Unknown"
        )

        governor_id = first_value(
            item.get("governor_id"),
            default=""
        )

        score = first_value(
            item.get("score"),
            item.get("value"),
            default=0
        )

        lines.append(
            f"**{index}. {name}** "
            f"`{governor_id}`\n"
            f"Score: **{format_number(score)}**"
        )

    if not lines:

        await interaction.followup.send(
            "❌ Ranking is empty."
        )

        return

    embed = discord.Embed(
        title=f"🏆 {board}",
        description="\n\n".join(lines),
        color=discord.Color.gold()
    )

    embed.set_footer(
        text=f"Kingdom {kid}"
    )

    await interaction.followup.send(
        embed=embed
    )


# =========================================================
# RENDER HEALTH CHECK
# =========================================================

async def health_handler(request):

    return web.Response(
        text="Kingshot Discord Bot is running."
    )


async def start_health_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health_handler
    )

    app.router.add_get(
        "/health",
        health_handler
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

    logger.info(
        "Health server started on port %s",
        PORT
    )

    return runner


# =========================================================
# MAIN
# =========================================================

async def main():

    health_runner = await start_health_server()

    try:

        await api.start()

        await bot.start(
            DISCORD_TOKEN
        )

    finally:

        await api.close()

        await bot.close()

        await health_runner.cleanup()


if __name__ == "__main__":

    try:
        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        logger.info(
            "Bot stopped."
        )
