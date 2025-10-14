import os
import random
import asyncio
import re
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ------------- Config -------------
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # optional

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.messages = True
INTENTS.message_content = False
INTENTS.voice_states = True

# Number of preparation sets
PREP_PAIRS = 4  # <<< 4 parties perso
# Limits
PREP_VOICE_LIMIT = 10      # "Préparation i"
SIDE_VOICE_LIMIT = 5       # "Préparation i - Attaque/Défense"

# ---- Voice creator (salon perso) ----
CREATE_VOICE_NAME = "➕ Créer un salon"  # lobby à rejoindre pour créer son salon
TEMP_DELETE_AFTER = 60                   # auto-suppression si vide (en s)
temp_rooms: Dict[int, dict] = {}         # vc_id -> {"owner": int, "private": bool, "limit": int, "wl": set[int], "bl": set[int], "text_id": int}
delete_tasks: Dict[int, asyncio.Task] = {}

# ------------- VALORANT Rank system -------------
TIERS = [
    ("iron",      "Iron",      3),
    ("bronze",    "Bronze",    3),
    ("silver",    "Silver",    3),
    ("gold",      "Gold",      3),
    ("platinum",  "Platinum",  3),
    ("diamond",   "Diamond",   3),
    ("ascendant", "Ascendant", 3),
    ("immortal",  "Immortal",  3),
    ("radiant",   "Radiant",   1),
]
TIER_INDEX = {key: i for i, (key, _, _) in enumerate(TIERS)}
TIER_META  = {key: (label, divs) for key, label, divs in TIERS}
TIER_ALIASES = {
    # FR -> EN
    "argent": "silver",
    "or": "gold",
    "platine": "platinum",
    "diamant": "diamond",
    # Abréviations usuelles
    "plat": "platinum",
    "dia": "diamond",
    "asc": "ascendant",
    "imm": "immortal",
    "imo": "immortal",
    "rad": "radiant",
    "gld": "gold",
    "silv": "silver",
    "bron": "bronze",
    "unrank": "iron",
}
ROMAN = {"i": 1, "ii": 2, "iii": 3}

def normalize_rank(text: str) -> Optional[str]:
    if not text:
        return None
    s = text.strip().lower().replace("-", " ").replace("_", " ")
    parts = [p for p in s.split() if p]
    if not parts:
        return None
    tier_key = TIER_ALIASES.get(parts[0], parts[0])
    if tier_key not in TIER_INDEX:
        return None
    label, divs = TIER_META[tier_key]
    div = None
    if divs > 1 and len(parts) >= 2:
        p = parts[1]
        if p.isdigit():
            div = int(p)
        else:
            div = ROMAN.get(p, None)
    if divs == 1:
        return label
    if div is None:
        div = 1
    div = max(1, min(divs, div))
    return f"{label} {div}"

def rank_value(display: str) -> int:
    if not display:
        return 0
    s = display.lower()
    for key, (label, divs) in TIER_META.items():
        if label.lower() in s:
            tier_idx = TIER_INDEX[key]
            if divs == 1:
                d = divs
            else:
                d = 0
                for tok in s.split():
                    if tok.isdigit():
                        d = int(tok)
                if d == 0:
                    d = 1
                d = max(1, min(divs, d))
            return tier_idx * 100 + int((d / divs) * 100)
    return 0

ROLE_COLORS = {
    "Iron": 0x7A7A7A,
    "Bronze": 0x8C5A3C,
    "Silver": 0xA7B4C0,
    "Gold": 0xD4AF37,
    "Platinum": 0x47C1B2,
    "Diamond": 0x5EC1FF,
    "Ascendant": 0x6AD16A,
    "Immortal": 0xB45FFF,
    "Radiant": 0xFFF26B,
}

# ------------- Branding / DA (The Witcher) -------------
ROLE_NAMES = {
    "admin": "Admin",
    "orga": "Orga PP",
    "staff": "Staff",
    "joueur": "Joueur",
    "spectateur": "Spectateur",
    "team_a": "Équipe Attaque",
    "team_b": "Équipe Défense",
}

SERVER_BRAND_NAME = os.getenv("SERVER_BRAND_NAME", "Arène de Kaer Morhen")
BOT_NICKNAME = os.getenv("BOT_NICKNAME", "WOLF-BOT")

CAT_WELCOME_NAME = "🐺・KAER MORHEN"
CAT_COMMU_NAME = "🍻・TAVERNE"
CAT_FUN_NAME = "🎻・BALLADES"
CAT_PP_NAME = "🛡️・CONTRATS (P-P)"

WELCOME_CHANNELS = [
    ("🐺・bienvenue", "text"),
    ("🕯️・règlement", "text"),
    ("🪙・auto-rôles", "text"),
    ("📣・annonces", "text"),
    ("🏰・table-ronde", "text"),
    ("🆘・support", "text"),
    ("🍷・passiflore", "text"),
]

COMMU_CHANNELS = [
    ("🍻・taverne", "text"),
    ("🖼️・médias", "text"),
    ("🪙・échanges", "text"),
    ("🎯・scrims", "text"),
    ("🏆・ranked", "text"),
    ("🧩・commandes", "text"),
    ("💡・suggestions", "text"),
    ("🔥・chasse-sauvage", "text"),
    ("🔗・vos-réseaux", "text"),
]

PP_TEXT = [
    ("🛡️・contrats-pp", "text"),
    ("📜・règlement-pp", "text"),
    ("🏷️・party-code", "text"),
    ("🎲・roulette-maps", "text"),
    ("🧭・demande-orga-pp", "text"),
]

VALORANT_MAPS = [
    "Ascent", "Bind", "Haven", "Split", "Lotus", "Sunset", "Icebox", "Breeze", "Pearl", "Fracture", "Corrode", "Abyss"
]

# ------------- Helpers -------------
def normalize_slug(name: str) -> str:
    seps = ["・", "｜", "|", "—", "-", "•"]
    for s in seps:
        name = name.replace(s, " ")
    return " ".join(name.lower().split())

def find_text_channel_by_slug(category: discord.CategoryChannel, slug: str):
    wanted = slug.lower()
    for ch in category.text_channels:
        if wanted in normalize_slug(ch.name):
            return ch
    return None

async def ensure_roles(guild: discord.Guild) -> Dict[str, discord.Role]:
    """Create/update key roles with desired permissions."""
    existing = {r.name: r for r in guild.roles}
    result: Dict[str, discord.Role] = {}

    perms_admin = discord.Permissions(administrator=True)
    perms_orga = discord.Permissions(move_members=True, mute_members=True, deafen_members=True)
    perms_none = discord.Permissions.none()

    desired = {
        "Admin": perms_admin,
        "Orga PP": perms_orga,
        "Staff": perms_none,
        "Joueur": perms_none,
        "Spectateur": perms_none,
        "Équipe Attaque": perms_none,
        "Équipe Défense": perms_none,
    }

    for name, perms in desired.items():
        role = existing.get(name)
        if role is None:
            role = await guild.create_role(name=name, permissions=perms, reason="Setup roles with permissions")
        else:
            try:
                if role.permissions != perms:
                    await role.edit(permissions=perms, reason="Update role permissions")
            except discord.Forbidden:
                pass
        if name == "Admin": result["admin"] = role
        elif name == "Orga PP": result["orga"] = role
        elif name == "Staff": result["staff"] = role
        elif name == "Joueur": result["joueur"] = role
        elif name == "Spectateur": result["spectateur"] = role
        elif name == "Équipe Attaque": result["team_a"] = role
        elif name == "Équipe Défense": result["team_b"] = role

    return result

def is_rank_role_name(name: str) -> bool:
    n = name.lower()
    for _, (label, _) in TIER_META.items():
        if label.lower() in n:
            return True
    return False

async def apply_rank_role(guild: discord.Guild, member: discord.Member, display: str):
    for r in list(member.roles):
        if is_rank_role_name(r.name):
            try:
                await member.remove_roles(r, reason="Update peak rank")
            except discord.Forbidden:
                pass
    role = discord.utils.get(guild.roles, name=display)
    if role is None:
        base_label = display.split()[0]
        color_hex = ROLE_COLORS.get(base_label, 0x5865F2)
        role = await guild.create_role(name=display, color=discord.Color(color_hex), reason="Create rank role")
    await member.add_roles(role, reason="Set peak rank")

async def create_category_with_channels(guild: discord.Guild, cat_name: str, items: List[tuple]) -> discord.CategoryChannel:
    category = discord.utils.get(guild.categories, name=cat_name)
    if category is None:
        category = await guild.create_category(cat_name, reason="Setup 5v5 bot")
    existing_text = {c.name for c in category.text_channels}
    existing_voice = {c.name for c in category.voice_channels}
    for name, kind in items:
        if kind == "text" and name not in existing_text:
            await guild.create_text_channel(name, category=category)
        elif kind == "voice" and name not in existing_voice:
            await guild.create_voice_channel(name, category=category)
    return category

async def create_pp_voice_structure(guild: discord.Guild, category: discord.CategoryChannel):
    """Create N sets of voice + text channels: Préparation i (10), Attaque (5), Défense (5), prépa-i-chat (text)."""
    existing_voice = {c.name: c for c in category.voice_channels}
    existing_text = {c.name: c for c in category.text_channels}
    for i in range(1, PREP_PAIRS + 1):
        prep_name = f"Préparation {i}"
        atk_name = f"Préparation {i} - Attaque"
        def_name = f"Préparation {i} - Défense"
        chat_name = f"💬・préparation-{i}-chat"

        if prep_name not in existing_voice:
            await guild.create_voice_channel(prep_name, category=category, user_limit=PREP_VOICE_LIMIT)
        else:
            try:
                await existing_voice[prep_name].edit(user_limit=PREP_VOICE_LIMIT, reason="Apply PREP_VOICE_LIMIT")
            except discord.Forbidden:
                pass
        if atk_name not in existing_voice:
            await guild.create_voice_channel(atk_name, category=category, user_limit=SIDE_VOICE_LIMIT)
        else:
            try:
                await existing_voice[atk_name].edit(user_limit=SIDE_VOICE_LIMIT, reason="Apply SIDE_VOICE_LIMIT")
            except discord.Forbidden:
                pass
        if def_name not in existing_voice:
            await guild.create_voice_channel(def_name, category=category, user_limit=SIDE_VOICE_LIMIT)
        else:
            try:
                await existing_voice[def_name].edit(user_limit=SIDE_VOICE_LIMIT, reason="Apply SIDE_VOICE_LIMIT")
            except discord.Forbidden:
                pass
        if chat_name not in existing_text:
            await guild.create_text_channel(chat_name, category=category)

async def apply_pp_limits(guild: discord.Guild, category: discord.CategoryChannel, prep_limit: int, side_limit: int):
    for vc in category.voice_channels:
        try:
            if vc.name.startswith("Préparation ") and (" - Attaque" in vc.name or " - Défense" in vc.name):
                await vc.edit(user_limit=side_limit, reason="Update side voice limit")
            elif vc.name.startswith("Préparation ") and (" - " not in vc.name):
                await vc.edit(user_limit=prep_limit, reason="Update prep voice limit")
        except discord.Forbidden:
            pass

def balance_teams(members: List[discord.Member]) -> Tuple[List[discord.Member], List[discord.Member]]:
    def member_value(m: discord.Member) -> int:
        best = 0
        for r in m.roles:
            if is_rank_role_name(r.name):
                v = rank_value(r.name)
                if v > best:
                    best = v
        return best
    scored = sorted([(m, member_value(m)) for m in members], key=lambda x: x[1], reverse=True)
    a, b = [], []
    sa = sb = 0
    for m, v in scored:
        if sa <= sb:
            a.append(m); sa += v
        else:
            b.append(m); sb += v
    return a, b

# ------------- Rules texts -------------
SERVER_RULES_TEXT = """**RÈGLEMENT DU SERVEUR — ARÈNE DE KAER MORHEN**

**1) Respect absolu** — pas d’insultes, attaques perso, propos haineux (racisme, sexisme, homophobie, etc.).
**2) Zéro toxicité en vocal** — pas d’écrasement micro, cris, soundboard abusif. Push-to-talk recommandé.
**3) Jeu propre** — pas de triche, ghosting, stream-snipe, macro/logiciels interdits.
**4) Contenu & pubs** — pas de NSFW/illégal. La pub est limitée au salon `#vos-réseaux`.
**5) Pseudos & avatars** — pas d’usurpation ni contenu choquant. Garde un pseudo proche de ton IGN.
**6) Staff** — les décisions des **Orga PP** / **Staff** priment pour la bonne tenue des parties.
**7) Sanctions** — avertissement → mute → kick → ban selon la gravité / récidive.
**8) Signalements** — passe par `🆘・support` (précise date, salon, pseudo, preuve si possible).

Le détail des règles pour les **Parties Perso** est dans `📜・règlement-pp`.
Bon jeu, et reste digne d’un sorceleur 🐺 !"""

PP_RULES_TEXT = """**RÈGLEMENT PARTIES PERSO — CONTRATS DE SORCELEUR (VALORANT)**

1) **Respect / Zéro Toxicité** — pas d'insultes, harcèlement, racisme/sexisme. Fair-play avant tout.
2) **Pas de triche / ghost / stream-snipe** — logiciel interdit, macro, infos inter-équipes proscrites.
3) **Peak ELO honnête** — règle ton *peak* via `/set_rank` (ex: `Asc 1`, `Silver 2`, `Radiant`). L’équilibrage s’en sert.
4) **Pseudo cohérent** — pseudo Discord ≈ pseudo in-game pour fluidifier l’orga.
5) **Vocal** — **Attaque** et **Défense** pendant la game. **Préparation** pour briefing / picks.
6) **Party Code** — uniquement dans le salon dédié. Pas de diffusion publique.
7) **AFK / Grief** — signalez en `#support`. Récidive = sanctions.
8) **Staff / Orga** — leurs décisions priment pour garantir une bonne expérience.
9) **Sanctions graduées** — avertissement → mute → kick → ban selon gravité.

En rejoignant une game, vous acceptez ces règles. Bonne chasse !"""

async def post_server_rules(channel: discord.TextChannel):
    try:
        msg = await channel.send(SERVER_RULES_TEXT)
        try:
            await msg.pin()
        except discord.Forbidden:
            pass
    except discord.Forbidden:
        pass

async def post_rules_pp(channel: discord.TextChannel):
    try:
        msg = await channel.send(PP_RULES_TEXT)
        try:
            await msg.pin()
        except discord.Forbidden:
            pass
    except discord.Forbidden:
        pass

async def post_welcome_embed(channel: discord.TextChannel):
    embed = discord.Embed(
        title="🐺 Bienvenue à Kaer Morhen",
        description=(
            "Ici, les **contrats** se règlent avec fair-play.\n"
            "🌑 Les portes sont ouvertes.\n"
            "Reste digne, fais honneur au loup.\n"
        ),
        color=0x5865F2
    )
    embed.set_footer(text="Que la Chasse Sauvage vous épargne… GL HF !")
    try:
        msg = await channel.send(embed=embed)
        try:
            await msg.pin()
        except discord.Forbidden:
            pass
    except discord.Forbidden:
        pass

# ------------- UI for rank prompt -------------
class RankModal(discord.ui.Modal, title="Déclare ton peak ELO (VALORANT)"):
    rank_input = discord.ui.TextInput(
        label="Ex: Silver 1, Asc 1, Immortal 2, Radiant",
        placeholder="asc 1",
        required=True,
        max_length=32
    )
    def __init__(self, member_id: int):
        super().__init__()
        self.member_id = member_id
    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None and interaction.user.mutual_guilds:
            guild = interaction.user.mutual_guilds[0]
        if guild is None:
            return await interaction.response.send_message("Impossible de détecter le serveur.", ephemeral=True)
        display = normalize_rank(str(self.rank_input.value))
        if not display:
            return await interaction.response.send_message("Format invalide. Exemples : `Silver 1`, `Asc 1`, `Immortal 2`, `Radiant`.", ephemeral=True)
        member = guild.get_member(self.member_id) or interaction.user
        await apply_rank_role(guild, member, display)
        await interaction.response.send_message(f"✅ Ton peak a été enregistré : **{display}**.", ephemeral=True)

class RankPromptView(discord.ui.View):
    def __init__(self, member_id: int):
        super().__init__(timeout=None)
        self.member_id = member_id
    @discord.ui.button(label="🎯 Déclarer mon peak ELO (VALORANT)", style=discord.ButtonStyle.primary, custom_id="rankprompt:open")
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RankModal(member_id=self.member_id))

# ------------- Queues & Panel per set -------------
class SetQueues:
    def __init__(self):
        self.queues: Dict[int, List[int]] = defaultdict(list)
    def join(self, set_idx: int, user_id: int) -> bool:
        q = self.queues[set_idx]
        if user_id in q:
            return False
        q.append(user_id); return True
    def leave(self, set_idx: int, user_id: int) -> bool:
        q = self.queues[set_idx]
        if user_id not in q:
            return False
        q.remove(user_id); return True
    def ready(self, set_idx: int) -> bool:
        return len(self.queues[set_idx]) >= 10
    def pop10(self, set_idx: int) -> List[int]:
        q = self.queues[set_idx]
        players = q[:10]; self.queues[set_idx] = q[10:]; return players
    def list(self, set_idx: int) -> List[int]:
        return list(self.queues[set_idx])

set_queues = SetQueues()

def panel_embed(guild: discord.Guild, set_idx: int) -> discord.Embed:
    ids = set_queues.list(set_idx)
    mentions = []
    for uid in ids:
        m = guild.get_member(uid)
        mentions.append(m.mention if m else f"`{uid}`")
    em = discord.Embed(title=f"Préparation {set_idx} — File 5v5", description="Rejoins la file et lance une partie équilibrée.", color=0x5865F2)
    em.add_field(name=f"Joueurs ({len(ids)}/10)", value=", ".join(mentions) if mentions else "—", inline=False)
    em.set_footer(text="Boutons: Rejoindre • Quitter • Lancer • Finir")
    return em

class PanelView(discord.ui.View):
    """Panel PERSISTANT avec custom_id : fonctionne même après un restart (tant que le bot tourne)."""
    def __init__(self, set_idx: int):
        super().__init__(timeout=None)
        self.set_idx = set_idx

        b_join  = discord.ui.Button(label="✅ Rejoindre", style=discord.ButtonStyle.success,   custom_id=f"panel:join:{set_idx}")
        b_leave = discord.ui.Button(label="🚪 Quitter",   style=discord.ButtonStyle.secondary, custom_id=f"panel:leave:{set_idx}")
        b_start = discord.ui.Button(label="🚀 Lancer la partie", style=discord.ButtonStyle.primary, custom_id=f"panel:start:{set_idx}")
        b_end   = discord.ui.Button(label="🧹 Finir la partie",  style=discord.ButtonStyle.danger,  custom_id=f"panel:end:{set_idx}")

        async def cb_join(interaction: discord.Interaction):
            try:
                added = set_queues.join(self.set_idx, interaction.user.id)
                if not added:
                    return await interaction.response.send_message("Tu es déjà dans la file de cette préparation.", ephemeral=True)
                await interaction.response.send_message(f"Tu as rejoint la file (Préparation {self.set_idx}).", ephemeral=True)
                try:
                    await interaction.message.edit(embed=panel_embed(interaction.guild, self.set_idx), view=self)
                except Exception:
                    pass
            except Exception as e:
                if interaction.response.is_done():
                    await interaction.followup.send(f"❌ Erreur: {e}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ Erreur: {e}", ephemeral=True)

        async def cb_leave(interaction: discord.Interaction):
            try:
                removed = set_queues.leave(self.set_idx, interaction.user.id)
                if not removed:
                    return await interaction.response.send_message("Tu n'es pas dans la file.", ephemeral=True)
                await interaction.response.send_message(f"Tu as quitté la file (Préparation {self.set_idx}).", ephemeral=True)
                try:
                    await interaction.message.edit(embed=panel_embed(interaction.guild, self.set_idx), view=self)
                except Exception:
                    pass
            except Exception as e:
                if interaction.response.is_done():
                    await interaction.followup.send(f"❌ Erreur: {e}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ Erreur: {e}", ephemeral=True)

        async def cb_start(interaction: discord.Interaction):
            role_names = [r.name.lower() for r in interaction.user.roles]
            if 'orga pp' not in role_names:
                return await interaction.response.send_message("Tu dois avoir le rôle **Orga PP** pour lancer la partie.", ephemeral=True)

            await interaction.response.defer(ephemeral=True)
            try:
                if not set_queues.ready(self.set_idx):
                    need = 10 - len(set_queues.list(self.set_idx))
                    return await interaction.followup.send(f"Il manque **{need}** joueurs pour lancer.", ephemeral=True)

                guild = interaction.guild
                ids = set_queues.pop10(self.set_idx)
                members = [guild.get_member(uid) for uid in ids if guild.get_member(uid)]

                def member_value(m: discord.Member) -> int:
                    best = 0
                    for r in m.roles:
                        if is_rank_role_name(r.name):
                            best = max(best, rank_value(r.name))
                    return best
                scored = sorted([(m, member_value(m)) for m in members], key=lambda x: x[1], reverse=True)
                team_a, team_b = [], []
                sa = sb = 0
                for m, v in scored:
                    (team_a if sa <= sb else team_b).append(m)
                    if sa <= sb: sa += v
                    else: sb += v

                roles = await ensure_roles(guild)
                role_a, role_b = roles["team_a"], roles["team_b"]

                prefix = f"Préparation {self.set_idx}"
                attaque = discord.utils.get(guild.voice_channels, name=f"{prefix} - Attaque")
                defense = discord.utils.get(guild.voice_channels, name=f"{prefix} - Défense")

                for m in team_a:
                    try: await m.add_roles(role_a, reason="Match 5v5")
                    except discord.Forbidden: pass
                    if attaque and m.voice and m.voice.channel:
                        try: await m.move_to(attaque)
                        except discord.Forbidden: pass

                for m in team_b:
                    try: await m.add_roles(role_b, reason="Match 5v5")
                    except discord.Forbidden: pass
                    if defense and m.voice and m.voice.channel:
                        try: await m.move_to(defense)
                        except discord.Forbidden: pass

                em = discord.Embed(title=f"Match lancé — Préparation {self.set_idx}", description="Équipes équilibrées par peak ELO.", color=0x2ecc71)
                em.add_field(name="Équipe Attaque", value=", ".join(m.mention for m in team_a) or "—", inline=False)
                em.add_field(name="Équipe Défense", value=", ".join(m.mention for m in team_b) or "—", inline=False)
                await interaction.followup.send(embed=em)

                try:
                    await interaction.message.edit(embed=panel_embed(guild, self.set_idx), view=self)
                except Exception:
                    pass
            except Exception as e:
                await interaction.followup.send(f"❌ Erreur: {e}", ephemeral=True)

        async def cb_end(interaction: discord.Interaction):
            role_names = [r.name.lower() for r in interaction.user.roles]
            if 'orga pp' not in role_names:
                return await interaction.response.send_message("Tu dois avoir le rôle **Orga PP** pour terminer la partie.", ephemeral=True)

            await interaction.response.defer(ephemeral=True)
            try:
                guild = interaction.guild
                roles = await ensure_roles(guild)
                removed = 0
                for m in guild.members:
                    if roles["team_a"] in m.roles or roles["team_b"] in m.roles:
                        try:
                            await m.remove_roles(roles["team_a"], roles["team_b"], reason="Match terminé")
                            removed += 1
                        except discord.Forbidden:
                            pass
                await interaction.followup.send(f"Rôles d'équipe retirés de **{removed}** membres.")
                try:
                    await interaction.message.edit(embed=panel_embed(guild, self.set_idx), view=self)
                except Exception:
                    pass
            except Exception as e:
                await interaction.followup.send(f"❌ Erreur: {e}", ephemeral=True)

        b_join.callback = cb_join
        b_leave.callback = cb_leave
        b_start.callback = cb_start
        b_end.callback = cb_end

        self.add_item(b_join); self.add_item(b_leave); self.add_item(b_start); self.add_item(b_end)

# --------- VOICE CREATOR (salon perso) ----------
def _parse_user_id(s: str) -> Optional[int]:
    if not s:
        return None
    m = re.search(r"<@!?(\d+)>", s)
    if m:
        return int(m.group(1))
    if s.isdigit():
        return int(s)
    return None

async def _delete_room_after(vc: discord.VoiceChannel, delay: int = TEMP_DELETE_AFTER):
    await asyncio.sleep(delay)
    if vc.id in temp_rooms and len(vc.members) == 0:
        info = temp_rooms.pop(vc.id, None)
        try:
            await vc.delete(reason="Salon perso vide (auto-delete)")
        except Exception:
            pass
        if info and info.get("text_id"):
            tc = vc.guild.get_channel(info["text_id"])
            if isinstance(tc, discord.TextChannel):
                try:
                    await tc.delete(reason="Salon perso vide (auto-delete)")
                except Exception:
                    pass
    delete_tasks.pop(vc.id, None)

def control_embed(owner: discord.Member, vc: discord.VoiceChannel) -> discord.Embed:
    info = temp_rooms.get(vc.id, {})
    private = "Privé" if info.get("private") else "Public"
    limit = info.get("limit", 0) or "∞"
    em = discord.Embed(
        title="🎶 Contrôles du salon vocal",
        description=f"{owner.mention}, bienvenue dans **{vc.name}**.\n\n"
                    "• 🔒/🟢 Privé/Public\n"
                    "• 👥 Limite de membres\n"
                    "• ✅ Whitelist / ❌ Blacklist\n"
                    "• 📋 Voir les listes",
        color=0x2b2d31
    )
    em.add_field(name="Visibilité", value=private, inline=True)
    em.add_field(name="Limite", value=str(limit), inline=True)
    em.set_footer(text="Seul le créateur (ou Staff/Orga) peut utiliser ces contrôles.")
    return em

def can_control(user: discord.Member, guild: discord.Guild, vc_id: int) -> bool:
    info = temp_rooms.get(vc_id)
    if not info:
        return False
    if user.id == info["owner"]:
        return True
    names = {r.name.lower() for r in user.roles}
    if "admin" in names or "orga pp" in names or user.guild_permissions.manage_channels:
        return True
    return False

class LimitModal(discord.ui.Modal, title="Définir la limite (0 = illimité)"):
    val = discord.ui.TextInput(label="Nombre maximum", placeholder="0-99", required=True, max_length=3)
    def __init__(self, vc_id: int): super().__init__(); self.vc_id = vc_id
    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel): return await interaction.response.send_message("Salon introuvable.", ephemeral=True)
        if not can_control(interaction.user, interaction.guild, self.vc_id):
            return await interaction.response.send_message("Tu n'es pas autorisé.", ephemeral=True)
        try:
            n = int(str(self.val))
            n = max(0, min(99, n))
        except ValueError:
            return await interaction.response.send_message("Valeur invalide.", ephemeral=True)
        info = temp_rooms.get(vc.id, {})
        info["limit"] = n
        await vc.edit(user_limit=n, reason="Set limit (panel)")
        await interaction.response.send_message(f"Limite réglée à **{n or '∞'}**.", ephemeral=True)

class UserModal(discord.ui.Modal, title="Utilisateur (mention @ ou ID)"):
    u = discord.ui.TextInput(label="Utilisateur", placeholder="@pseudo ou 1234567890", required=True, max_length=40)
    def __init__(self, vc_id: int, action: str): super().__init__(); self.vc_id = vc_id; self.action = action
    async def on_submit(self, interaction: discord.Interaction):
        vc = interaction.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel): return await interaction.response.send_message("Salon introuvable.", ephemeral=True)
        if not can_control(interaction.user, interaction.guild, self.vc_id):
            return await interaction.response.send_message("Tu n'es pas autorisé.", ephemeral=True)
        uid = _parse_user_id(str(self.u))
        if not uid: return await interaction.response.send_message("Entrée invalide.", ephemeral=True)
        member = interaction.guild.get_member(uid)
        if not member: return await interaction.response.send_message("Membre introuvable.", ephemeral=True)
        info = temp_rooms.get(vc.id, {})
        if self.action == "wl":
            info.setdefault("wl", set()).add(uid)
            await vc.set_permissions(member, connect=True, view_channel=True)
            msg = f"{member.mention} ajouté à la **whitelist**."
        else:
            info.setdefault("bl", set()).add(uid)
            await vc.set_permissions(member, connect=False, view_channel=True)
            if member.voice and member.voice.channel and member.voice.channel.id == vc.id:
                try: await member.move_to(None)
                except Exception: pass
            msg = f"{member.mention} ajouté à la **blacklist**."
        await interaction.response.send_message(msg, ephemeral=True)

class ControlView(discord.ui.View):
    def __init__(self, vc_id: int):
        super().__init__(timeout=None)
        self.vc_id = vc_id

    @discord.ui.button(label="🔒 Rendre Privé", style=discord.ButtonStyle.danger, custom_id="rt:private")
    async def make_private(self, itx: discord.Interaction, btn: discord.ui.Button):
        vc = itx.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel): return await itx.response.send_message("Salon introuvable.", ephemeral=True)
        if not can_control(itx.user, itx.guild, self.vc_id): return await itx.response.send_message("Tu n'es pas autorisé.", ephemeral=True)
        info = temp_rooms.get(vc.id, {}); info["private"] = True
        await vc.set_permissions(itx.guild.default_role, connect=False, view_channel=True)
        for uid in info.get("wl", set()):
            m = itx.guild.get_member(uid)
            if m: await vc.set_permissions(m, connect=True, view_channel=True)
        await itx.response.send_message("Salon **privé**.", ephemeral=True)

    @discord.ui.button(label="🟢 Rendre Public", style=discord.ButtonStyle.success, custom_id="rt:public")
    async def make_public(self, itx: discord.Interaction, btn: discord.ui.Button):
        vc = itx.guild.get_channel(self.vc_id)
        if not isinstance(vc, discord.VoiceChannel): return await itx.response.send_message("Salon introuvable.", ephemeral=True)
        if not can_control(itx.user, itx.guild, self.vc_id): return await itx.response.send_message("Tu n'es pas autorisé.", ephemeral=True)
        info = temp_rooms.get(vc.id, {}); info["private"] = False
        await vc.set_permissions(itx.guild.default_role, connect=True, view_channel=True)
        await itx.response.send_message("Salon **public**.", ephemeral=True)

    @discord.ui.button(label="👥 Limite de Membres", style=discord.ButtonStyle.primary, custom_id="rt:limit")
    async def set_limit(self, itx: discord.Interaction, btn: discord.ui.Button):
        if not can_control(itx.user, itx.guild, self.vc_id): return await itx.response.send_message("Tu n'es pas autorisé.", ephemeral=True)
        await itx.response.send_modal(LimitModal(self.vc_id))

    @discord.ui.button(label="✅ Whitelist", style=discord.ButtonStyle.secondary, custom_id="rt:wl")
    async def add_whitelist(self, itx: discord.Interaction, btn: discord.ui.Button):
        if not can_control(itx.user, itx.guild, self.vc_id): return await itx.response.send_message("Tu n'es pas autorisé.", ephemeral=True)
        await itx.response.send_modal(UserModal(self.vc_id, "wl"))

    @discord.ui.button(label="❌ Blacklist", style=discord.ButtonStyle.secondary, custom_id="rt:bl")
    async def add_blacklist(self, itx: discord.Interaction, btn: discord.ui.Button):
        if not can_control(itx.user, itx.guild, self.vc_id): return await itx.response.send_message("Tu n'es pas autorisé.", ephemeral=True)
        await itx.response.send_modal(UserModal(self.vc_id, "bl"))

    @discord.ui.button(label="📋 Voir Whitelist", style=discord.ButtonStyle.secondary, custom_id="rt:viewwl")
    async def view_wl(self, itx: discord.Interaction, btn: discord.ui.Button):
        info = temp_rooms.get(self.vc_id, {})
        wl = [itx.guild.get_member(uid).mention for uid in info.get("wl", set()) if itx.guild.get_member(uid)]
        await itx.response.send_message("Whitelist : " + (", ".join(wl) if wl else "—"), ephemeral=True)

    @discord.ui.button(label="📋 Voir Blacklist", style=discord.ButtonStyle.secondary, custom_id="rt:viewbl")
    async def view_bl(self, itx: discord.Interaction, btn: discord.ui.Button):
        info = temp_rooms.get(self.vc_id, {})
        bl = [itx.guild.get_member(uid).mention for uid in info.get("bl", set()) if itx.guild.get_member(uid)]
        await itx.response.send_message("Blacklist : " + (", ".join(bl) if bl else "—"), ephemeral=True)

async def create_personal_room(member: discord.Member, lobby: discord.VoiceChannel):
    guild = member.guild
    cat = lobby.category
    base_name = f"🎶 {member.display_name}"

    # vocal public par défaut
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True),
        member: discord.PermissionOverwrite(view_channel=True, connect=True, move_members=True),
    }
    vc = await guild.create_voice_channel(base_name, category=cat, overwrites=overwrites, reason="Salon perso (create)")

    # --- chat de contrôle avec accès Orga/Admin ---
    roles = await ensure_roles(guild)
    text_name = f"🎛️-{member.name.lower().replace(' ', '-')}-control"
    t_over = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True),
    }
    if roles.get("orga"):
        t_over[roles["orga"]] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
    if roles.get("admin"):
        t_over[roles["admin"]] = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)

    tc = await guild.create_text_channel(text_name, category=cat, overwrites=t_over, reason="Chat de contrôle salon perso")

    temp_rooms[vc.id] = {"owner": member.id, "private": False, "limit": 0, "wl": set(), "bl": set(), "text_id": tc.id}
    await tc.send(embed=control_embed(member, vc), view=ControlView(vc.id))

    if member.voice and member.voice.channel:
        try:
            await member.move_to(vc)
        except discord.Forbidden:
            pass

# ------------- Bot -------------
class FiveBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)

    async def setup_hook(self):
        for i in range(1, PREP_PAIRS + 1):
            self.add_view(PanelView(i))
        # enregistrer la classe ControlView (persistant tant que le bot tourne)
        self.add_view(ControlView(0))

        if GUILD_ID:
            gid = int(GUILD_ID)
            self.tree.copy_global_to(guild=discord.Object(id=gid))
            await self.tree.sync(guild=discord.Object(id=gid))
        else:
            await self.tree.sync()

bot = FiveBot()

# ------------- Events -------------
@bot.event
async def on_member_join(member: discord.Member):
    try:
        view = RankPromptView(member.id)
        await member.send(
            "Bienvenue sur le serveur Valorant ! Déclare ton **peak ELO** pour obtenir le bon rôle. Tu peux aussi utiliser `/set_rank`.",
            view=view
        )
    except discord.Forbidden:
        pass
    try:
        target_cat = None
        for cat in member.guild.categories:
            if "KAER MORHEN" in cat.name.upper() or "WELCOME" in cat.name.upper():
                target_cat = cat; break
        if target_cat:
            ch = find_text_channel_by_slug(target_cat, "bienvenue")
            if ch and ch.permissions_for(member.guild.me).send_messages:
                await post_welcome_embed(ch)
    except Exception:
        pass

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    # création si on rejoint le lobby
    if after and after.channel and after.channel.name == CREATE_VOICE_NAME:
        await create_personal_room(member, after.channel)

    # suppression planifiée si un salon perso devient vide
    if before and before.channel and before.channel.id in temp_rooms and len(before.channel.members) == 0:
        vc = before.channel
        if vc.id not in delete_tasks:
            delete_tasks[vc.id] = asyncio.create_task(_delete_room_after(vc, TEMP_DELETE_AFTER))

# ------------- Slash Commands -------------
@bot.tree.command(description="Configurer les rôles, catégories, vocs et panneaux (thème Witcher).")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    await ensure_roles(guild)

    cat_welcome = await create_category_with_channels(guild, CAT_WELCOME_NAME, WELCOME_CHANNELS)
    cat_commu   = await create_category_with_channels(guild, CAT_COMMU_NAME,   COMMU_CHANNELS)
    cat_fun     = await create_category_with_channels(guild, CAT_FUN_NAME,     [("🎭・conte-auteurs", "text"), ("🎨・fan-art", "text")])
    cat_pp      = await create_category_with_channels(guild, CAT_PP_NAME,      PP_TEXT)
    await create_pp_voice_structure(guild, cat_pp)
    await apply_pp_limits(guild, cat_pp, PREP_VOICE_LIMIT, SIDE_VOICE_LIMIT)

    # Voice lobby "Créer un salon" dans la Taverne
    try:
        creator = discord.utils.get(cat_commu.voice_channels, name=CREATE_VOICE_NAME)
        if creator is None:
            await guild.create_voice_channel(CREATE_VOICE_NAME, category=cat_commu, reason="Salon créateur de salons persos")
    except discord.Forbidden:
        pass

    for i in range(1, PREP_PAIRS + 1):
        chat = discord.utils.get(cat_pp.text_channels, name=f"💬・préparation-{i}-chat")
        if chat:
            try:
                await chat.send(embed=panel_embed(guild, i), view=PanelView(i))
            except discord.Forbidden:
                pass

    try:
        bienv = find_text_channel_by_slug(cat_welcome, "bienvenue")
        await guild.edit(name=SERVER_BRAND_NAME, system_channel=bienv if bienv else guild.system_channel)
    except discord.Forbidden:
        pass

    try:
        me = guild.me
        if me and me.nick != BOT_NICKNAME:
            await me.edit(nick=BOT_NICKNAME, reason="Brand nickname")
    except discord.Forbidden:
        pass

    try:
        regles_server = find_text_channel_by_slug(cat_welcome, "règlement")
        if regles_server:
            await post_server_rules(regles_server)
        rules_channel = find_text_channel_by_slug(cat_pp, "règlement-pp")
        if rules_channel:
            await post_rules_pp(rules_channel)
        if bienv:
            await post_welcome_embed(bienv)
    except Exception:
        pass

    await interaction.followup.send("✅ Setup terminé + panneaux + salon '➕ Créer un salon' prêt.", ephemeral=True)

@bot.tree.command(description="(Re)poster les règles serveur et PP et les épingler.")
@app_commands.checks.has_permissions(manage_guild=True)
async def post_rules(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    cat_welcome = discord.utils.get(interaction.guild.categories, name=CAT_WELCOME_NAME)
    cat_pp = discord.utils.get(interaction.guild.categories, name=CAT_PP_NAME)
    if cat_welcome:
        ch = find_text_channel_by_slug(cat_welcome, "règlement")
        if ch:
            await post_server_rules(ch)
    if cat_pp:
        ch2 = find_text_channel_by_slug(cat_pp, "règlement-pp")
        if ch2:
            await post_rules_pp(ch2)
    await interaction.followup.send("Règles repostées et épinglées (si permissions).", ephemeral=True)

@bot.tree.command(description="Définir ton peak ELO (VALORANT).")
@app_commands.describe(valeur="Exemples: 'silver 1', 'asc 1', 'immortal 2', 'radiant'")
async def set_rank(interaction: discord.Interaction, valeur: str):
    display = normalize_rank(valeur)
    if not display:
        return await interaction.response.send_message("Format invalide. Exemples valides : `Silver 1`, `Asc 1`, `Immortal 2`, `Radiant`.", ephemeral=True)
    await apply_rank_role(interaction.guild, interaction.user, display)
    await interaction.response.send_message(f"✅ Peak enregistré : **{display}**", ephemeral=True)

@bot.tree.command(description="Voir le peak ELO d'un membre (via son rôle).")
@app_commands.describe(membre="Laisser vide pour toi-même.")
async def rank_show(interaction: discord.Interaction, membre: Optional[discord.Member] = None):
    m = membre or interaction.user
    best = None
    best_val = -1
    for r in m.roles:
        if is_rank_role_name(r.name):
            v = rank_value(r.name)
            if v > best_val:
                best = r.name; best_val = v
    if best is None:
        return await interaction.response.send_message(f"{m.mention} n'a pas encore de peak ELO.", ephemeral=True)
    await interaction.response.send_message(f"Peak ELO de {m.mention} : **{best}**", ephemeral=True)

@bot.tree.command(description="Tirer une map aléatoire du pool VALORANT.")
async def roulette(interaction: discord.Interaction):
    choice = random.choice(VALORANT_MAPS)
    await interaction.response.send_message(f"🗺️ Map tirée au sort : **{choice}**")

# ------------- Run -------------
def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN manquant. Mets-le dans .env")

    # --- stay alive ---
    try:
        from keep_alive import keep_alive
        keep_alive()
        print("[keep_alive] HTTP ping server started.")
    except Exception as e:
        print(f"[keep_alive] disabled: {e}")

    bot.run(TOKEN)

if __name__ == "__main__":
    main()
