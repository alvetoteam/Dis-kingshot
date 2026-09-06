import os
import asyncio
import logging
from datetime import datetime

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
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("kingshot-bot")


# =========================================================
# BASIC VALIDATION
# =========================================================

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing")

if not DISCORD_APPLICATION_ID:
    raise RuntimeError("DISCORD_APPLICATION_ID is missing")

if not MIGHTPULSE_API_KEY:
    raise RuntimeError("MIGHTPULSE_API_KEY is missing")


# =========================================================
# HELPERS
# =========================================================

def get_value(data, *keys, default=None):
    """
    Safely get the first existing value from a dictionary.
    """
    if not isinstance(data, dict):
        return default

    for key in keys:
        if key in data and data[key] is not None:
            return data[key]

    return default


def first_value(*values, default=None):
    """
    Return the first non-None/non-empty value.
    """
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


def format_percent(value):
    if value is None:
        return "N/A"

    try:
        return f"{float(value):,.2f}%"
    except (ValueError, TypeError):
        return str(value)


def valid_url(value):
    """
    Discord requires a valid URL for thumbnails/images.
    """
    if not isinstance(value, str):
        return None

    value = value.strip()

    if value.startswith("https://") or value.startswith("http://"):
        return value

    return None


def format_stars(hero):
    stars = first_value(
        hero.get("stars"),
        hero.get("star"),
        default=0
    )

    try:
        stars = int(stars)
        return "⭐" * max(0, stars)
    except (ValueError, TypeError):
        return str(stars)


def get_player_data(data):
    if not isinstance(data, dict):
        return {}

    player = data.get("player")

    if isinstance(player, dict):
        return player

    return data


def get_hero_list(data):
    """
    Heroes are normally returned at top-level.
    Also supports nested player.heroes if present.
    """
    if not isinstance(data, dict):
        return []

    heroes = data.get("heroes")

    if isinstance(heroes, list):
        return heroes

    player = data.get("player")

    if isinstance(player, dict):
        heroes = player.get("heroes")

        if isinstance(heroes, list):
            return heroes

    return []


# =========================================================
# HERO HELPERS
# =========================================================

def hero_power(hero):
    value = hero.get("power")

    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0


def total_hero_power(data):
    heroes = get_hero_list(data)

    return sum(hero_power(hero) for hero in heroes)


def strongest_hero(data):
    heroes = get_hero_list(data)

    if not heroes:
        return None

    return max(heroes, key=hero_power)


def get_hero_gear(hero):
    gear = hero.get("gear")

    if not isinstance(gear, list):
        return []

    return gear


def get_exclusive_gear(hero):
    gear = hero.get("exclusive_gear")

    if not isinstance(gear, dict):
        return None

    return gear


def format_skill_levels(hero):
    skills = hero.get("skill_levels")

    if not isinstance(skills, list) or not skills:
        return "N/A"

    output = []

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

        output.append(f"Skill {skill_id}: Lv.{level}")

    return "\n".join(output) if output else "N/A"


def format_hero_gear(hero):
    gear_list = get_hero_gear(hero)

    if not gear_list:
        return "No hero gear"

    lines = []

    for item in gear_list:
        if not isinstance(item, dict):
            continue

        slot = first_value(
            item.get("slot"),
            item.get("name"),
            default="Unknown"
        )

        name = first_value(
            item.get("name"),
            default="Gear"
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
            item.get("quality_key"),
            item.get("quality"),
            default=""
        )

        red = item.get("red")

        red_text = " 🔴" if red else ""

        line = (
            f"**{slot}**: {name}"
            f" +{enhancement}"
            f" | Refine {refine}"
        )

        if quality:
            line += f" | {quality}"

        line += red_text

        lines.append(line)

    return "\n".join(lines) if lines else "No hero gear"


def format_exclusive_gear(hero):
    exclusive = get_exclusive_gear(hero)

    if not exclusive:
        return "No Exclusive Gear"

    name = first_value(
        exclusive.get("name"),
        default="Exclusive Gear"
    )

    level = first_value(
        exclusive.get("level"),
        default=0
    )

    atk = exclusive.get("atk_ratio")
    hp = exclusive.get("hp_ratio")
    defense = exclusive.get("def_ratio")
    power = exclusive.get("power_ratio")

    lines = [
        f"**{name}**",
        f"Level: **{level}**"
    ]

    if atk is not None:
        lines.append(f"ATK: {format_percent(atk)}")

    if hp is not None:
        lines.append(f"HP: {format_percent(hp)}")

    if defense is not None:
        lines.append(f"DEF: {format_percent(defense)}")

    if power is not None:
        lines.append(f"Power: {format_percent(power)}")

    return "\n".join(lines)


# =========================================================
# GOVERNOR GEAR HELPERS
# =========================================================

def get_gov_gear(data):
    """
    Governor Gear is returned as a top-level section:
    {
        "gov_gear": {
            "hidden": false,
            "message": "...",
            "items": [...]
        }
    }
    """

    if not isinstance(data, dict):
        return {}

    gov_gear = data.get("gov_gear")

    if isinstance(gov_gear, dict):
        return gov_gear

    player = data.get("player")

    if isinstance(player, dict):
        gov_gear = player.get("gov_gear")

        if isinstance(gov_gear, dict):
            return gov_gear

    return {}


def get_gov_gear_items(data):
    gov_gear = get_gov_gear(data)

    items = gov_gear.get("items")

    if isinstance(items, list):
        return items

    return []


def gov_gear_total_score(data):
    items = get_gov_gear_items(data)

    total = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        try:
            total += float(item.get("score") or 0)
        except (ValueError, TypeError):
            pass

    return total


def gov_gear_total_combat(data):
    items = get_gov_gear_items(data)

    total = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        try:
            total += float(item.get("combat") or 0)
        except (ValueError, TypeError):
            pass

    return total


def gov_gear_total_gems(data):
    items = get_gov_gear_items(data)

    total = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        gems = item.get("gems")

        if isinstance(gems, list):
            total += len(gems)

    return total


def gov_gear_slot_map(data):
    items = get_gov_gear_items(data)

    result = {}

    for item in items:
        if not isinstance(item, dict):
            continue

        slot = first_value(
            item.get("slot"),
            item.get("name"),
            default="Unknown"
        )

        result[str(slot)] = item

    return result


def format_gov_gear_item(item):
    if not isinstance(item, dict):
        return "N/A"

    name = first_value(
        item.get("name"),
        default="Governor Gear"
    )

    slot = first_value(
        item.get("slot"),
        default=""
    )

    quality = first_value(
        item.get("quality_label"),
        item.get("quality"),
        default=""
    )

    tier = first_value(
        item.get("tier"),
        default=0
    )

    star = first_value(
        item.get("star"),
        default=0
    )

    strength = first_value(
        item.get("strength_level"),
        default=0
    )

    score = first_value(
        item.get("score"),
        default=0
    )

    combat = first_value(
        item.get("combat"),
        default=0
    )

    gems = item.get("gems")

    if not isinstance(gems, list):
        gems = []

    lines = []

    if slot:
        lines.append(f"**{slot}** — {name}")
    else:
        lines.append(f"**{name}**")

    if quality:
        lines.append(f"Quality: {quality}")

    lines.append(
        f"Tier: **{tier}** | ⭐ **{star}** | Strength: **{strength}**"
    )

    lines.append(
        f"Score: **{format_number(score)}** | Combat: **{format_number(combat)}**"
    )

    lines.append(
        f"💎 Gems: **{len(gems)}**"
    )

    return "\n".join(lines)


def build_gov_gear_embed(data, player_data):
    embed = discord.Embed(
        title="👑 Governor Gear",
        description="Governor Gear information",
        color=discord.Color.gold()
    )

    gov_gear = get_gov_gear(data)

    if not gov_gear:
        embed.description = "No Governor Gear data returned by the API."
        return embed

    if gov_gear.get("hidden"):
        embed.description = (
            gov_gear.get("message")
            or "Governor Gear information is hidden."
        )

        return embed

    items = get_gov_gear_items(data)

    if not items:
        embed.description = "No Governor Gear found."
        return embed

    total_score = gov_gear_total_score(data)
    total_combat = gov_gear_total_combat(data)
    total_gems = gov_gear_total_gems(data)

    embed.add_field(
        name="📊 Totals",
        value=(
            f"Score: **{format_number(total_score)}**\n"
            f"Combat: **{format_number(total_combat)}**\n"
            f"💎 Gems: **{total_gems}**"
        ),
        inline=False
    )

    for item in items:
        if not isinstance(item, dict):
            continue

        field_name = first_value(
            item.get("slot"),
            item.get("name"),
            default="Governor Gear"
        )

        value = format_gov_gear_item(item)

        # Discord field values have a 1024 character limit
        if len(value) > 1000:
            value = value[:997] + "..."

        embed.add_field(
            name=f"🛡️ {field_name}",
            value=value,
            inline=True
        )

    avatar = valid_url(
        first_value(
            player_data.get("avatar_url"),
            player_data.get("avatar")
        )
    )

    if avatar:
        embed.set_thumbnail(url=avatar)

    return embed


# =========================================================
# MIGHTPULSE API
# =========================================================

class MightPulseAPI:

    def __init__(self, api_key):
        self.api_key = api_key
        self.session = None

    async def start(self):
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)

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

        logger.info("GET %s", endpoint)

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
                        logger.error(
                            "Invalid JSON response: %s",
                            text[:500]
                        )

                        return {
                            "ok": False,
                            "error": "Invalid JSON response"
                        }

                if response.status == 401:
                    return {
                        "ok": False,
                        "error": "Unauthorized",
                        "message": (
                            "MightPulse API key is invalid or "
                            "the current plan does not allow this request."
                        )
                    }

                if response.status == 403:
                    return {
                        "ok": False,
                        "error": "Forbidden",
                        "message": "MightPulse denied access to this request."
                    }

                if response.status == 404:
                    return {
                        "ok": False,
                        "error": "Not Found",
                        "message": "The requested player/data was not found."
                    }

                if response.status == 429:
                    return {
                        "ok": False,
                        "error": "Rate Limited",
                        "message": "MightPulse rate limit reached. Try again later."
                    }

                logger.error(
                    "MightPulse HTTP %s: %s",
                    response.status,
                    text[:1000]
                )

                return {
                    "ok": False,
                    "error": f"HTTP {response.status}",
                    "message": text[:500]
                }

        except asyncio.TimeoutError:
            return {
                "ok": False,
                "error": "Timeout",
                "message": "MightPulse API request timed out."
            }

        except aiohttp.ClientError as e:
            logger.exception("HTTP error")

            return {
                "ok": False,
                "error": "Connection Error",
                "message": str(e)
            }

        except Exception as e:
            logger.exception("Unexpected API error")

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

    async def get_kingdom_ranks(self, kid, limit=100):
        return await self.get(
            f"/kingdoms/{kid}/ranks",
            params={
                "limit": limit
            }
        )


api = MightPulseAPI(MIGHTPULSE_API_KEY)


# =========================================================
# DISCORD BOT
# =========================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    application_id=int(DISCORD_APPLICATION_ID)
)


# =========================================================
# PLAYER HERO VIEW
# =========================================================

class HeroView(discord.ui.View):

    def __init__(self, heroes, player_data, timeout=300):
        super().__init__(timeout=timeout)

        self.heroes = heroes
        self.player_data = player_data
        self.index = 0

        self.update_buttons()

    def update_buttons(self):
        self.previous_button.disabled = self.index <= 0
        self.next_button.disabled = self.index >= len(self.heroes) - 1

    def create_embed(self):

        hero = self.heroes[self.index]

        name = first_value(
            hero.get("name"),
            default="Unknown Hero"
        )

        level = first_value(
            hero.get("level"),
            default="?"
        )

        power = hero_power(hero)

        quality = first_value(
            hero.get("quality"),
            default=""
        )

        exclusive = get_exclusive_gear(hero)

        embed = discord.Embed(
            title=f"🦸 {name}",
            color=discord.Color.blue()
        )

        embed.description = (
            f"Hero **{self.index + 1}/{len(self.heroes)}**"
        )

        embed.add_field(
            name="📊 Hero Stats",
            value=(
                f"Level: **{level}**\n"
                f"Stars: {format_stars(hero)}\n"
                f"Power: **{format_number(power)}**"
                + (
                    f"\nQuality: **{quality}**"
                    if quality
                    else ""
                )
            ),
            inline=False
        )

        # -------------------------------------------------
        # HERO GEAR
        # -------------------------------------------------

        hero_gear = format_hero_gear(hero)

        if len(hero_gear) > 1000:
            hero_gear = hero_gear[:997] + "..."

        embed.add_field(
            name="⚔️ Hero Gear",
            value=hero_gear,
            inline=False
        )

        # -------------------------------------------------
        # EXCLUSIVE GEAR
        # -------------------------------------------------

        exclusive_text = format_exclusive_gear(hero)

        if len(exclusive_text) > 1000:
            exclusive_text = exclusive_text[:997] + "..."

        embed.add_field(
            name="🔱 Exclusive Gear",
            value=exclusive_text,
            inline=False
        )

        # -------------------------------------------------
        # SKILLS
        # -------------------------------------------------

        skills = format_skill_levels(hero)

        embed.add_field(
            name="✨ Skills",
            value=skills[:1000],
            inline=False
        )

        # -------------------------------------------------
        # HERO ICON
        # -------------------------------------------------

        hero_icon = valid_url(
            first_value(
                hero.get("icon"),
                hero.get("icon_url"),
                hero.get("image")
            )
        )

        if hero_icon:
            embed.set_thumbnail(url=hero_icon)

        else:
            avatar = valid_url(
                first_value(
                    self.player_data.get("avatar_url"),
                    self.player_data.get("avatar")
                )
            )

            if avatar:
                embed.set_thumbnail(url=avatar)

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
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if self.index > 0:
            self.index -= 1

        await self.refresh(interaction)

    @discord.ui.button(
        label="Next",
        emoji="➡️",
        style=discord.ButtonStyle.primary
    )
    async def next_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if self.index < len(self.heroes) - 1:
            self.index += 1

        await self.refresh(interaction)


# =========================================================
# BOT EVENTS
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
        logger.exception("Failed to sync commands")


@bot.event
async def on_disconnect():
    logger.warning("Discord disconnected")


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
        error = data.get("error", "Unknown error")
        message = data.get("message", "")

        await interaction.followup.send(
            f"❌ **{error}**\n{message}"
        )

        return

    player = get_player_data(data)

    name = first_value(
        player.get("nick_name"),
        player.get("nickname"),
        default="Unknown"
    )

    kid = first_value(
        player.get("kid"),
        default="N/A"
    )

    fid = first_value(
        player.get("fid"),
        default="N/A"
    )

    power = player.get("power")
    kills = player.get("kills")

    tc = first_value(
        player.get("town_center_level"),
        player.get("castle_level"),
        default="N/A"
    )

    vip = player.get("vip")

    alliance = player.get("alliance")

    alliance_name = "No Alliance"

    if isinstance(alliance, dict):
        alliance_name = first_value(
            alliance.get("name"),
            alliance.get("abbr"),
            alliance.get("tag"),
            default="No Alliance"
        )

    elif isinstance(alliance, str):
        alliance_name = alliance

    online = player.get("online")

    online_text = "🟢 Online" if online else "⚫ Offline"

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
        value=f"`{kid}`",
        inline=True
    )

    embed.add_field(
        name="FID",
        value=f"`{fid}`",
        inline=True
    )

    embed.add_field(
        name="⚡ Power",
        value=f"**{format_number(power)}**",
        inline=True
    )

    embed.add_field(
        name="☠️ Kills",
        value=f"**{format_number(kills)}**",
        inline=True
    )

    embed.add_field(
        name="🏰 Town Center",
        value=f"**{tc}**",
        inline=True
    )

    embed.add_field(
        name="👑 VIP",
        value=f"**{vip if vip is not None else 'N/A'}**",
        inline=True
    )

    embed.add_field(
        name="🤝 Alliance",
        value=f"**{alliance_name}**",
        inline=True
    )

    embed.add_field(
        name="📡 Status",
        value=online_text,
        inline=True
    )

    avatar = valid_url(
        first_value(
            player.get("avatar_url"),
            player.get("avatar")
        )
    )

    if avatar:
        embed.set_thumbnail(url=avatar)

    await interaction.followup.send(
        embed=embed
    )

    # =====================================================
    # HEROES
    # =====================================================

    heroes = get_hero_list(data)

    if heroes:

        heroes_embed = discord.Embed(
            title="🦸 Heroes",
            description=(
                f"Total Heroes: **{len(heroes)}**\n"
                f"Total Hero Power: **{format_number(total_hero_power(data))}**"
            ),
            color=discord.Color.purple()
        )

        best = strongest_hero(data)

        if best:
            best_name = first_value(
                best.get("name"),
                default="Unknown"
            )

            heroes_embed.add_field(
                name="🏆 Strongest Hero",
                value=(
                    f"**{best_name}**\n"
                    f"Power: **{format_number(hero_power(best))}**"
                ),
                inline=False
            )

        await interaction.followup.send(
            embed=heroes_embed,
            view=HeroView(
                heroes,
                player
            )
        )

    # =====================================================
    # GOVERNOR GEAR
    # =====================================================

    gov_embed = build_gov_gear_embed(
        data,
        player
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
            f"❌ Player 1 error: "
            f"{data1.get('error', 'Unknown error')}\n"
            f"{data1.get('message', '')}"
        )

        return

    if not data2.get("ok", True):

        await interaction.followup.send(
            f"❌ Player 2 error: "
            f"{data2.get('error', 'Unknown error')}\n"
            f"{data2.get('message', '')}"
        )

        return

    p1 = get_player_data(data1)
    p2 = get_player_data(data2)

    name1 = first_value(
        p1.get("nick_name"),
        p1.get("nickname"),
        default=governor_id_1
    )

    name2 = first_value(
        p2.get("nick_name"),
        p2.get("nickname"),
        default=governor_id_2
    )

    # =====================================================
    # BASIC STATS
    # =====================================================

    power1 = float(p1.get("power") or 0)
    power2 = float(p2.get("power") or 0)

    kills1 = float(p1.get("kills") or 0)
    kills2 = float(p2.get("kills") or 0)

    tc1 = float(
        first_value(
            p1.get("town_center_level"),
            p1.get("castle_level"),
            default=0
        ) or 0
    )

    tc2 = float(
        first_value(
            p2.get("town_center_level"),
            p2.get("castle_level"),
            default=0
        ) or 0
    )

    vip1 = float(p1.get("vip") or 0)
    vip2 = float(p2.get("vip") or 0)

    hero_power1 = total_hero_power(data1)
    hero_power2 = total_hero_power(data2)

    hero_count1 = len(get_hero_list(data1))
    hero_count2 = len(get_hero_list(data2))

    gov_score1 = gov_gear_total_score(data1)
    gov_score2 = gov_gear_total_score(data2)

    gov_combat1 = gov_gear_total_combat(data1)
    gov_combat2 = gov_gear_total_combat(data2)

    gov_gems1 = gov_gear_total_gems(data1)
    gov_gems2 = gov_gear_total_gems(data2)

    # =====================================================
    # ALLIANCE
    # =====================================================

    def get_alliance_name(player):

        alliance = player.get("alliance")

        if isinstance(alliance, dict):
            return first_value(
                alliance.get("name"),
                alliance.get("abbr"),
                alliance.get("tag"),
                default="No Alliance"
            )

        if isinstance(alliance, str):
            return alliance

        return "No Alliance"

    alliance1 = get_alliance_name(p1)
    alliance2 = get_alliance_name(p2)

    # =====================================================
    # STRONGEST HERO
    # =====================================================

    best1 = strongest_hero(data1)
    best2 = strongest_hero(data2)

    best_name1 = (
        first_value(best1.get("name"), default="N/A")
        if best1
        else "N/A"
    )

    best_name2 = (
        first_value(best2.get("name"), default="N/A")
        if best2
        else "N/A"
    )

    best_power1 = hero_power(best1) if best1 else 0
    best_power2 = hero_power(best2) if best2 else 0

    # =====================================================
    # SCORE
    # =====================================================

    score1 = 0
    score2 = 0

    if power1 > power2:
        score1 += 1
    elif power2 > power1:
        score2 += 1

    if kills1 > kills2:
        score1 += 1
    elif kills2 > kills1:
        score2 += 1

    if tc1 > tc2:
        score1 += 1
    elif tc2 > tc1:
        score2 += 1

    if vip1 > vip2:
        score1 += 1
    elif vip2 > vip1:
        score2 += 1

    if hero_power1 > hero_power2:
        score1 += 1
    elif hero_power2 > hero_power1:
        score2 += 1

    if hero_count1 > hero_count2:
        score1 += 1
    elif hero_count2 > hero_count1:
        score2 += 1

    if gov_score1 > gov_score2:
        score1 += 1
    elif gov_score2 > gov_score1:
        score2 += 1

    if gov_combat1 > gov_combat2:
        score1 += 1
    elif gov_combat2 > gov_combat1:
        score2 += 1

    # =====================================================
    # MAIN COMPARISON EMBED
    # =====================================================

    embed = discord.Embed(
        title="⚔️ Player Comparison",
        color=discord.Color.gold()
    )

    embed.add_field(
        name=f"👤 {name1}",
        value=f"`{governor_id_1}`",
        inline=True
    )

    embed.add_field(
        name="VS",
        value="⚔️",
        inline=True
    )

    embed.add_field(
        name=f"👤 {name2}",
        value=f"`{governor_id_2}`",
        inline=True
    )

    # -----------------------------------------------------
    # BASIC
    # -----------------------------------------------------

    embed.add_field(
        name="⚡ Power",
        value=(
            f"**{format_number(power1)}**\n"
            f"vs\n"
            f"**{format_number(power2)}**"
        ),
        inline=True
    )

    embed.add_field(
        name="☠️ Kills",
        value=(
            f"**{format_number(kills1)}**\n"
            f"vs\n"
            f"**{format_number(kills2)}**"
        ),
        inline=True
    )

    embed.add_field(
        name="🏰 Town Center",
        value=(
            f"**{format_number(tc1)}**\n"
            f"vs\n"
            f"**{format_number(tc2)}**"
        ),
        inline=True
    )

    embed.add_field(
        name="👑 VIP",
        value=(
            f"**{format_number(vip1)}**\n"
            f"vs\n"
            f"**{format_number(vip2)}**"
        ),
        inline=True
    )

    # -----------------------------------------------------
    # HERO
    # -----------------------------------------------------

    embed.add_field(
        name="🦸 Hero Power",
        value=(
            f"**{format_number(hero_power1)}**\n"
            f"vs\n"
            f"**{format_number(hero_power2)}**"
        ),
        inline=True
    )

    embed.add_field(
        name="🦸 Hero Count",
        value=(
            f"**{hero_count1}**\n"
            f"vs\n"
            f"**{hero_count2}**"
        ),
        inline=True
    )

    embed.add_field(
        name="🏆 Strongest Hero",
        value=(
            f"**{best_name1}**\n"
            f"{format_number(best_power1)} Power\n"
            f"vs\n"
            f"**{best_name2}**\n"
            f"{format_number(best_power2)} Power"
        ),
        inline=True
    )

    # -----------------------------------------------------
    # ALLIANCE
    # -----------------------------------------------------

    embed.add_field(
        name="🤝 Alliance",
        value=(
            f"**{alliance1}**\n"
            f"vs\n"
            f"**{alliance2}**"
        ),
        inline=True
    )

    # -----------------------------------------------------
    # GOVERNOR GEAR
    # -----------------------------------------------------

    embed.add_field(
        name="👑 Governor Gear Score",
        value=(
            f"**{format_number(gov_score1)}**\n"
            f"vs\n"
            f"**{format_number(gov_score2)}**"
        ),
        inline=True
    )

    embed.add_field(
        name="⚔️ Governor Gear Combat",
        value=(
            f"**{format_number(gov_combat1)}**\n"
            f"vs\n"
            f"**{format_number(gov_combat2)}**"
        ),
        inline=True
    )

    embed.add_field(
        name="💎 Governor Gear Gems",
        value=(
            f"**{gov_gems1}**\n"
            f"vs\n"
            f"**{gov_gems2}**"
        ),
        inline=True
    )

    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    if score1 > score2:
        result = f"🏆 **{name1} wins {score1} - {score2}**"

    elif score2 > score1:
        result = f"🏆 **{name2} wins {score2} - {score1}**"

    else:
        result = f"🤝 **Draw {score1} - {score2}**"

    embed.add_field(
        name="🏆 Overall Result",
        value=result,
        inline=False
    )

    await interaction.followup.send(
        embed=embed
    )

    # =====================================================
    # GOVERNOR GEAR SLOT COMPARISON
    # =====================================================

    gear1 = gov_gear_slot_map(data1)
    gear2 = gov_gear_slot_map(data2)

    all_slots = list(
        dict.fromkeys(
            list(gear1.keys()) +
            list(gear2.keys())
        )
    )

    if all_slots:

        gear_compare = discord.Embed(
            title="👑 Governor Gear Comparison",
            description=(
                f"**{name1}** vs **{name2}**"
            ),
            color=discord.Color.orange()
        )

        for slot in all_slots:

            item1 = gear1.get(slot)
            item2 = gear2.get(slot)

            score_a = (
                float(item1.get("score") or 0)
                if item1
                else 0
            )

            score_b = (
                float(item2.get("score") or 0)
                if item2
                else 0
            )

            if item1:
                text1 = (
                    f"{first_value(item1.get('name'), default='Gear')}\n"
                    f"Tier: {item1.get('tier', 0)} | "
                    f"⭐ {item1.get('star', 0)} | "
                    f"Strength: {item1.get('strength_level', 0)}\n"
                    f"Score: **{format_number(score_a)}**"
                )
            else:
                text1 = "No Gear"

            if item2:
                text2 = (
                    f"{first_value(item2.get('name'), default='Gear')}\n"
                    f"Tier: {item2.get('tier', 0)} | "
                    f"⭐ {item2.get('star', 0)} | "
                    f"Strength: {item2.get('strength_level', 0)}\n"
                    f"Score: **{format_number(score_b)}**"
                )
            else:
                text2 = "No Gear"

            value = (
                f"**{name1}**\n"
                f"{text1}\n\n"
                f"**{name2}**\n"
                f"{text2}"
            )

            if len(value) > 1000:
                value = value[:997] + "..."

            gear_compare.add_field(
                name=f"🛡️ {slot}",
                value=value,
                inline=False
            )

        await interaction.followup.send(
            embed=gear_compare
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
            f"❌ **{data.get('error', 'Unknown error')}**\n"
            f"{data.get('message', '')}"
        )

        return

    info = data.get("info") or {}

    name = first_value(
        info.get("name"),
        default=tag
    )

    abbr = first_value(
        info.get("abbr"),
        default=tag
    )

    power = info.get("power")
    count = info.get("count")

    leader = first_value(
        info.get("leader_name"),
        default="N/A"
    )

    power_rank = info.get("power_rank")

    embed = discord.Embed(
        title=f"🤝 {name}",
        description=f"Tag: **{abbr}**",
        color=discord.Color.green()
    )

    embed.add_field(
        name="🌍 Kingdom",
        value=f"**{kid}**",
        inline=True
    )

    embed.add_field(
        name="⚡ Power",
        value=f"**{format_number(power)}**",
        inline=True
    )

    embed.add_field(
        name="👥 Members",
        value=f"**{count if count is not None else 'N/A'}**",
        inline=True
    )

    embed.add_field(
        name="👑 Leader",
        value=f"**{leader}**",
        inline=True
    )

    embed.add_field(
        name="🏆 Power Rank",
        value=f"**{power_rank if power_rank is not None else 'N/A'}**",
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

    # =====================================================
    # ROSTER
    # =====================================================

    members = data.get("members")

    if not isinstance(members, list):
        members = data.get("roster")

    if isinstance(members, list) and members:

        members = sorted(
            members,
            key=lambda x: float(
                x.get("power") or 0
            ),
            reverse=True
        )

        lines = []

        for index, member in enumerate(
            members[:25],
            start=1
        ):

            if not isinstance(member, dict):
                continue

            nick = first_value(
                member.get("nick_name"),
                default="Unknown"
            )

            member_power = member.get("power")

            tc = first_value(
                member.get("town_center_level"),
                default="?"
            )

            lines.append(
                f"**{index}. {nick}** — "
                f"{format_number(member_power)} Power "
                f"| TC {tc}"
            )

        if lines:

            roster_embed = discord.Embed(
                title="👥 Alliance Roster",
                description="\n".join(lines),
                color=discord.Color.green()
            )

            roster_embed.set_footer(
                text=f"Showing top {len(lines)} members by power"
            )

            await interaction.followup.send(
                embed=roster_embed
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
            f"❌ **{data.get('error', 'Unknown error')}**\n"
            f"{data.get('message', '')}"
        )

        return

    kingdom = data.get("kingdom")

    if not isinstance(kingdom, dict):
        kingdom = data

    name = first_value(
        kingdom.get("name"),
        default=f"Kingdom {kid}"
    )

    embed = discord.Embed(
        title=f"🌍 {name}",
        description=f"Kingdom **{kid}**",
        color=discord.Color.blue()
    )

    fields = [
        (
            "⚡ Power",
            kingdom.get("power")
        ),
        (
            "👥 Players",
            kingdom.get("player_count")
        ),
        (
            "🤝 Alliances",
            kingdom.get("alliance_count")
        ),
        (
            "📅 Age",
            (
                f"{kingdom.get('age_days')} days"
                if kingdom.get("age_days") is not None
                else None
            )
        ),
        (
            "📈 Avg Power",
            kingdom.get("avg_power")
        ),
        (
            "🏆 Power Rank",
            kingdom.get("power_rank")
        ),
        (
            "🔥 Activity Rank",
            kingdom.get("activity_rank")
        ),
        (
            "❤️ Health",
            kingdom.get("health")
        ),
        (
            "☠️ Kills",
            kingdom.get("kills")
        ),
        (
            "🦸 Hero Power",
            kingdom.get("hero_power")
        ),
        (
            "⚔️ Troop Power",
            kingdom.get("troop_power")
        ),
        (
            "🏗️ Building Power",
            kingdom.get("building_power")
        ),
        (
            "🔬 Research Power",
            kingdom.get("research_power")
        ),
        (
            "👑 Governor Gear",
            kingdom.get("governor_gear_power")
        ),
        (
            "💎 Governor Charm",
            kingdom.get("governor_charm_power")
        ),
        (
            "🐾 Pet Power",
            kingdom.get("pet_power")
        ),
        (
            "🧪 Mystic Trial",
            kingdom.get("mystic_trial")
        ),
        (
            "🏝️ Island Prosperity",
            kingdom.get("island_prosperity")
        )
    ]

    for field_name, value in fields:

        if value is None:
            continue

        if isinstance(value, (int, float)):
            value = format_number(value)

        embed.add_field(
            name=field_name,
            value=f"**{value}**",
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
    board="Leaderboard name"
)
async def rank_command(
    interaction: discord.Interaction,
    kid: str,
    board: str = "personal_power"
):

    await interaction.response.defer()

    data = await api.get_kingdom_ranks(
        kid
    )

    if not data.get("ok", True):

        await interaction.followup.send(
            f"❌ **{data.get('error', 'Unknown error')}**\n"
            f"{data.get('message', '')}"
        )

        return

    leaderboards = data.get("leaderboards")

    if isinstance(leaderboards, dict):

        selected = leaderboards.get(board)

        if selected is None:
            selected = leaderboards.get(
                board.lower()
            )

    else:
        selected = None

    if selected is None:

        if isinstance(data.get("rankings"), list):
            selected = data.get("rankings")

        elif isinstance(data.get("items"), list):
            selected = data.get("items")

    if isinstance(selected, dict):
        selected = selected.get("items") or selected.get("entries")

    if not isinstance(selected, list):

        await interaction.followup.send(
            "❌ No ranking data found for this board."
        )

        return

    lines = []

    for index, item in enumerate(
        selected[:25],
        start=1
    ):

        if not isinstance(item, dict):
            continue

        name = first_value(
            item.get("nick_name"),
            item.get("name"),
            item.get("governor_name"),
            default="Unknown"
        )

        governor_id = first_value(
            item.get("governor_id"),
            item.get("id"),
            default=""
        )

        value = first_value(
            item.get("value"),
            item.get("power"),
            item.get("score"),
            item.get("kills"),
            default=0
        )

        lines.append(
            f"**{index}. {name}** "
            f"`{governor_id}` — **{format_number(value)}**"
        )

    if not lines:

        await interaction.followup.send(
            "❌ Ranking is empty."
        )

        return

    embed = discord.Embed(
        title=f"🏆 {board}",
        description="\n".join(lines),
        color=discord.Color.gold()
    )

    embed.set_footer(
        text=f"Kingdom {kid}"
    )

    await interaction.followup.send(
        embed=embed
    )


# =========================================================
# HEALTH SERVER FOR RENDER
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

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    logger.info(
        "Health server running on port %s",
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
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("Bot stopped.")
