# bot.py
import os
import re
import random
import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ===================== Config =====================
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")  # optionnel

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True               # ⚠️ active "Server Members Intent" dans le Dev Portal
INTENTS.voice_states = True
INTENTS.messages = True
INTENTS.message_content = False

# Parties perso
PREP_PAIRS = 4
PREP_VOICE_LIMIT = 10
SIDE_VOICE_LIMIT  = 5

# Créateur de salon vocal
CREATE_VOICE_NAME   = "➕ Créer un salon"
TEMP_DELETE_GRACE_S = 60  # secondes après salon vide avant suppression

# DA / Noms de catégories
SERVER_BRAND_NAME = os.getenv("SERVER_BRAND_NAME", "Arène de Kaer Morhen")
BOT_NICKNAME      = os.getenv("BOT_NICKNAME", "WOLF-BOT")

CAT_WELCOME_NAME = "🐺・KAER MORHEN"
CAT_COMMU_NAME   = "🍻・TAVERNE"
CAT_FUN_NAME     = "🎻・BALLADES"
CAT_PP_NAME      = "🛡️・CONTRATS (P-P)"

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

# Mots-clés pour détecter les vocs (souple avec emojis/variantes)
ATTACK_KEYWORDS  = {"attaque", "att", "atk"}
DEFENSE_KEYWORDS = {"défense", "defense", "def"}

def slug(s: str) -> str:
    for sep in ["・","｜","|","—","-","•","·","• "]:
        s = s.replace(sep, " ")
    return " ".join(s.lower().split())

def has_attack(name: str) -> bool:
    n = slug(name)
    return any(k in n for k in ATTACK_KEYWORDS)

def has_defense(name: str) -> bool:
    n = slug(name)
    return any(k in n for k in DEFENSE_KEYWORDS)

# ===================== Ranks (Valorant) =====================
TIERS = [
    ("iron","Iron",3), ("bronze","Bronze",3), ("silver","Silver",3),
    ("gold","Gold",3), ("platinum","Platinum",3), ("diamond","Diamond",3),
    ("ascendant","Ascendant",3), ("immortal","Immortal",3), ("radiant","Radiant",1),
]
TIER_INDEX = {k:i for i,(k,_,_) in enumerate(TIERS)}
TIER_META  = {k:(label,divs) for k,label,divs in TIERS}
TIER_ALIASES = {
    "argent":"silver","or":"gold","platine":"platinum","diamant":"diamond",
    "plat":"platinum","dia":"diamond","asc":"ascendant","imm":"immortal","imo":"immortal",
    "rad":"radiant","gld":"gold","silv":"silver","bron":"bronze","unrank":"iron",
}
ROMAN = {"i":1,"ii":2,"iii":3}
ROLE_COLORS = {
    "Iron":0x7A7A7A,"Bronze":0x8C5A3C,"Silver":0xA7B4C0,"Gold":0xD4AF37,
    "Platinum":0x47C1B2,"Diamond":0x5EC1FF,"Ascendant":0x6AD16A,
    "Immortal":0xB45FFF,"Radiant":0xFFF26B
}

def normalize_rank(t: str) -> Optional[str]:
    if not t: return None
    s = t.strip().lower().replace("-", " ").replace("_", " ")
    parts = [p for p in s.split() if p]
    if not parts: return None
    tier = TIER_ALIASES.get(parts[0], parts[0])
    if tier not in TIER_INDEX: return None
    label, divs = TIER_META[tier]
    if divs == 1: return label
    div = None
    if len(parts) >= 2:
        p = parts[1]
        div = int(p) if p.isdigit() else ROMAN.get(p)
    if div is None: div = 1
    div = max(1, min(divs, div))
    return f"{label} {div}"

def rank_value(display: str) -> int:
    if not display: return 0
    s = display.lower()
    for key,(label,divs) in TIER_META.items():
        if label.lower() in s:
            ti = TIER_INDEX[key]
            if divs == 1: d = 1
            else:
                d = 1
                for tok in s.split():
                    if tok.isdigit(): d = int(tok)
                d = max(1, min(divs, d))
            return ti*100 + int((d/divs)*100)
    return 0

def is_rank_role_name(name: str) -> bool:
    return any(L.lower() in name.lower() for _,L,_ in TIERS)

async def apply_rank_role(guild: discord.Guild, member: discord.Member, display: str):
    # remove old rank roles
    for r in list(member.roles):
        if is_rank_role_name(r.name):
            try: await member.remove_roles(r, reason="Update peak rank")
            except discord.Forbidden: pass
    base = display.split()[0]
    col = discord.Color(ROLE_COLORS.get(base, 0x5865F2))
    role = discord.utils.get(guild.roles, name=display)
    if role is None:
        role = await guild.create_role(name=display, color=col, reason="Create rank role")
    await member.add_roles(role, reason="Set peak rank")

# ===================== Catégories / Channels =====================
def pp_category(guild: discord.Guild) -> Optional[discord.CategoryChannel]:
    return discord.utils.get(guild.categories, name=CAT_PP_NAME)

def find_text_by_slug(cat: discord.CategoryChannel, target: str):
    t = target.lower()
    for ch in cat.text_channels:
        if t in slug(ch.name): return ch
    return None

async def create_category_with_channels(guild: discord.Guild, name: str, items: List[tuple]) -> discord.CategoryChannel:
    cat = discord.utils.get(guild.categories, name=name)
    if cat is None:
        cat = await guild.create_category(name, reason="Setup bot")
    exist_text = {c.name for c in cat.text_channels}
    exist_voice = {c.name for c in cat.voice_channels}
    for nm, kind in items:
        if kind == "text" and nm not in exist_text:
            await guild.create_text_channel(nm, category=cat)
        elif kind == "voice" and nm not in exist_voice:
            await guild.create_voice_channel(nm, category=cat)
    return cat

async def ensure_party_text_channels(guild: discord.Guild, cat: discord.CategoryChannel, count: int = 4):
    existing = {slug(c.name): c for c in cat.text_channels}
    for i in range(1, count+1):
        s = f"salon partie {i}"
        if s not in existing:
            await guild.create_text_channel(f"• salon-partie-{i}", category=cat, reason="PP party chat")

def get_party_text_channel(guild: discord.Guild, i: int) -> Optional[discord.TextChannel]:
    """Trouve le salon texte 'partie i' (robuste aux emojis/variantes)."""
    cat = pp_category(guild)
    if not cat:
        return None
    target = f"salon partie {i}"
    for ch in cat.text_channels:
        if target in slug(ch.name):
            return ch
    return None

def find_group_channels_for_set(guild: discord.Guild, i: int) -> Tuple[Optional[discord.VoiceChannel], Optional[discord.VoiceChannel], Optional[discord.VoiceChannel]]:
    """Retourne (Préparation i, Attaque, Défense) en bornant entre Préparation i et la suivante."""
    cat = pp_category(guild)
    if not cat: return None, None, None
    vcs = sorted(cat.voice_channels, key=lambda c: c.position)
    # Index de Préparation i
    prep_idx = next((k for k, vc in enumerate(vcs) if slug(vc.name) == slug(f"préparation {i}")), None)
    if prep_idx is None: return None, None, None
    # Limite haute = prochaine Préparation
    next_idx = next((k for k in range(prep_idx+1, len(vcs)) if slug(vcs[k].name).startswith("préparation ")), len(vcs))
    window = vcs[prep_idx+1:next_idx]
    atk = next((vc for vc in window if has_attack(vc.name)), None)
    defn = next((vc for vc in window if has_defense(vc.name)), None)
    return vcs[prep_idx], atk, defn

async def create_pp_voice_structure(guild: discord.Guild, cat: discord.CategoryChannel):
    """Crée/ajuste Préparation i + Attaque/Défense (avec emojis) et applique les limites."""
    for i in range(1, PREP_PAIRS+1):
        # Préparation i
        prep = discord.utils.find(lambda vc: slug(vc.name)==slug(f"préparation {i}"), cat.voice_channels)
        if not prep:
            await guild.create_voice_channel(f"Préparation {i}", category=cat, user_limit=PREP_VOICE_LIMIT)
        else:
            try: await prep.edit(user_limit=PREP_VOICE_LIMIT)
            except discord.Forbidden: pass

        # ⚔ / 🛡
        _, atk, defn = find_group_channels_for_set(guild, i)
        if not atk:
            await guild.create_voice_channel("⚔ · Attaque", category=cat, user_limit=SIDE_VOICE_LIMIT)
        else:
            if not has_attack(atk.name):
                try: await atk.edit(name="⚔ · Attaque")
                except: pass
            try: await atk.edit(user_limit=SIDE_VOICE_LIMIT)
            except: pass
        if not defn:
            await guild.create_voice_channel("🛡 · Défense", category=cat, user_limit=SIDE_VOICE_LIMIT)
        else:
            if not has_defense(defn.name):
                try: await defn.edit(name="🛡 · Défense")
                except: pass
            try: await defn.edit(user_limit=SIDE_VOICE_LIMIT)
            except: pass

# ===================== Rôles clés =====================
async def ensure_roles(guild: discord.Guild) -> Dict[str, discord.Role]:
    existing = {r.name: r for r in guild.roles}
    perms_admin = discord.Permissions(administrator=True)
    perms_orga  = discord.Permissions(move_members=True, mute_members=True, deafen_members=True)
    perms_none  = discord.Permissions.none()
    desired = {
        "Admin": perms_admin,
        "Orga PP": perms_orga,
        "Staff": perms_none,
        "Joueur": perms_none,
        "Spectateur": perms_none,
        "Équipe Attaque": perms_none,
        "Équipe Défense": perms_none,
    }
    out = {}
    for name, perms in desired.items():
        role = existing.get(name)
        if role is None:
            role = await guild.create_role(name=name, permissions=perms, reason="Setup roles")
        else:
            try:
                if role.permissions != perms:
                    await role.edit(permissions=perms, reason="Update role perms")
            except discord.Forbidden:
                pass
        key = {"Admin":"admin","Orga PP":"orga","Staff":"staff","Joueur":"joueur","Spectateur":"spectateur","Équipe Attaque":"team_a","Équipe Défense":"team_b"}[name]
        out[key] = role
    return out

# ===================== File 5v5 & Panneau =====================
class SetQueues:
    def __init__(self): self.queues: Dict[int, List[int]] = {i: [] for i in range(1, PREP_PAIRS+1)}
    def join(self, i:int, uid:int)->bool:
        q=self.queues[i]
        if uid in q: return False
        q.append(uid); return True
    def leave(self,i:int,uid:int)->bool:
        q=self.queues[i]
        if uid not in q: return False
        q.remove(uid); return True
    def ready(self,i:int)->bool: return len(self.queues[i])>=10
    def pop10(self,i:int)->List[int]:
        q=self.queues[i]; p=q[:10]; self.queues[i]=q[10:]; return p
    def list(self,i:int)->List[int]: return list(self.queues[i])

set_queues = SetQueues()

def panel_embed(guild:discord.Guild,i:int)->discord.Embed:
    ids=set_queues.list(i)
    mentions=[]
    for uid in ids:
        m=guild.get_member(uid)
        mentions.append(m.mention if m else f"`{uid}`")
    em=discord.Embed(title=f"Préparation {i} — File 5v5", description="Rejoins la file et lance une partie équilibrée.", color=0x5865F2)
    em.add_field(name=f"Joueurs ({len(ids)}/10)", value=", ".join(mentions) if mentions else "—", inline=False)
    em.set_footer(text="Boutons: Rejoindre • Quitter • Lancer • Finir")
    return em

async def ensure_panel_once(chat:discord.TextChannel, embed:discord.Embed, view:discord.ui.View):
    try:
        pins = await chat.pins()
        for m in pins:
            if m.author==chat.guild.me and m.embeds and m.embeds[0].title==embed.title:
                return
    except: pass
    async for m in chat.history(limit=30):
        if m.author==chat.guild.me and m.embeds and m.embeds[0].title==embed.title:
            return
    msg = await chat.send(embed=embed, view=view)
    try: await msg.pin()
    except: pass

async def purge_channel_messages(chat: discord.TextChannel, keep_pins: bool = True, limit: int = 500):
    """Efface les messages récents du salon (sauf pins si keep_pins=True)."""
    pins = []
    if keep_pins:
        try:
            pins = await chat.pins()
        except:
            pins = []
    pinned_ids = {m.id for m in pins}
    try:
        await chat.purge(limit=limit, check=(lambda m: m.id not in pinned_ids))
    except discord.Forbidden:
        pass
    except Exception:
        pass

class PanelView(discord.ui.View):
    def __init__(self,set_idx:int):
        super().__init__(timeout=None); self.set_idx=set_idx
        b_join  = discord.ui.Button(label="✅ Rejoindre", style=discord.ButtonStyle.success,   custom_id=f"panel:join:{set_idx}")
        b_leave = discord.ui.Button(label="🚪 Quitter",  style=discord.ButtonStyle.secondary, custom_id=f"panel:leave:{set_idx}")
        b_start = discord.ui.Button(label="🚀 Lancer la partie", style=discord.ButtonStyle.primary, custom_id=f"panel:start:{set_idx}")
        b_end   = discord.ui.Button(label="🧹 Finir la partie",  style=discord.ButtonStyle.danger,  custom_id=f"panel:end:{set_idx}")

        async def cb_join(inter:discord.Interaction):
            if not set_queues.join(self.set_idx, inter.user.id):
                return await inter.response.send_message("Tu es déjà dans la file.", ephemeral=True)
            await inter.response.send_message(f"Tu as rejoint la file (Préparation {self.set_idx}).", ephemeral=True)
            try: await inter.message.edit(embed=panel_embed(inter.guild,self.set_idx), view=self)
            except: pass

        async def cb_leave(inter:discord.Interaction):
            if not set_queues.leave(self.set_idx, inter.user.id):
                return await inter.response.send_message("Tu n'es pas dans la file.", ephemeral=True)
            await inter.response.send_message("Tu as quitté la file.", ephemeral=True)
            try: await inter.message.edit(embed=panel_embed(inter.guild,self.set_idx), view=self)
            except: pass

        async def cb_start(inter:discord.Interaction):
            roles = {r.name.lower() for r in inter.user.roles}
            if 'orga pp' not in roles and not inter.user.guild_permissions.administrator:
                return await inter.response.send_message("Orga PP requis.", ephemeral=True)
            await inter.response.defer(ephemeral=True)
            if not set_queues.ready(self.set_idx):
                need = 10 - len(set_queues.list(self.set_idx))
                return await inter.followup.send(f"Il manque **{need}** joueurs.", ephemeral=True)
            guild = inter.guild
            ids = set_queues.pop10(self.set_idx)
            members = [guild.get_member(u) for u in ids if guild.get_member(u)]

            def val(m:discord.Member)->int:
                best=0
                for r in m.roles:
                    if is_rank_role_name(r.name): best=max(best, rank_value(r.name))
                return best
            scored=sorted([(m,val(m)) for m in members], key=lambda x:x[1], reverse=True)
            A,B=[],[]; sa=sb=0
            for m,v in scored:
                if sa<=sb: A.append(m); sa+=v
                else: B.append(m); sb+=v

            key_roles = await ensure_roles(guild)
            roleA, roleB = key_roles["team_a"], key_roles["team_b"]
            _, atk, defn = find_group_channels_for_set(guild, self.set_idx)

            for m in A:
                try: await m.add_roles(roleA)
                except: pass
                if atk and m.voice and m.voice.channel:
                    try: await m.move_to(atk)
                    except: pass
            for m in B:
                try: await m.add_roles(roleB)
                except: pass
                if defn and m.voice and m.voice.channel:
                    try: await m.move_to(defn)
                    except: pass

            em=discord.Embed(title=f"Match lancé — Préparation {self.set_idx}", description="Équilibrage par peak ELO.", color=0x2ecc71)
            em.add_field(name="Équipe Attaque", value=", ".join(m.mention for m in A) or "—", inline=False)
            em.add_field(name="Équipe Défense", value=", ".join(m.mention for m in B) or "—", inline=False)
            await inter.followup.send(embed=em)

            try: await inter.message.edit(embed=panel_embed(guild,self.set_idx), view=self)
            except: pass

        async def cb_end(inter:discord.Interaction):
            roles = {r.name.lower() for r in inter.user.roles}
            if 'orga pp' not in roles and not inter.user.guild_permissions.administrator:
                return await inter.response.send_message("Orga PP requis.", ephemeral=True)
            await inter.response.defer(ephemeral=True)
            guild = inter.guild
            key_roles = await ensure_roles(guild)
            removed = 0
            for m in guild.members:
                if key_roles["team_a"] in m.roles or key_roles["team_b"] in m.roles:
                    try:
                        await m.remove_roles(key_roles["team_a"], key_roles["team_b"], reason="Match terminé")
                        removed += 1
                    except: pass
            # Reset file + votes
            set_queues.queues[self.set_idx] = []
            if self.set_idx in map_votes:
                mv = map_votes[self.set_idx]
                mv.voters.clear(); mv.yes=0; mv.no=0; mv.locked=False

            # CLEAR le salon-partie-i (messages non épinglés) et replanter les panneaux
            chat = get_party_text_channel(guild, self.set_idx)
            if chat:
                await purge_channel_messages(chat, keep_pins=True, limit=500)
                # Repost panel + roulette tout de suite
                await ensure_panel_once(chat, panel_embed(guild, self.set_idx), PanelView(self.set_idx))
                await ensure_mapvote_panel_once(chat, self.set_idx)

            await inter.followup.send(f"Rôles retirés de **{removed}** membres. File réinitialisée. Salon-partie nettoyé.", ephemeral=True)
            try: await inter.message.edit(embed=panel_embed(guild,self.set_idx), view=self)
            except: pass

        b_join.callback=cb_join; b_leave.callback=cb_leave; b_start.callback=cb_start; b_end.callback=cb_end
        self.add_item(b_join); self.add_item(b_leave); self.add_item(b_start); self.add_item(b_end)

# ===================== Embeds de base =====================
SERVER_RULES_TEXT = """**RÈGLEMENT DU SERVEUR — ARÈNE DE KAER MORHEN**
Respect, jeu propre, pas de triche/ghost, pubs limitées, décisions Orga PP/Staff priment.
Le détail des règles PP est dans `📜・règlement-pp`. Bon jeu 🐺 !
"""
PP_RULES_TEXT = """**RÈGLEMENT PARTIES PERSO — VALORANT**
Fair-play, pas de triche, vocal Attaque/Défense, party-code privé, sanctions graduées.
"""

async def post_server_rules(ch:discord.TextChannel):
    try:
        msg = await ch.send(SERVER_RULES_TEXT)
        try: await msg.pin()
        except: pass
    except: pass

async def post_rules_pp(ch:discord.TextChannel):
    try:
        msg = await ch.send(PP_RULES_TEXT)
        try: await msg.pin()
        except: pass
    except: pass

# ===================== Peak ELO dans auto-rôles =====================
class RankModal(discord.ui.Modal, title="Déclare ton peak ELO (VALORANT)"):
    rank_input = discord.ui.TextInput(label="Ex: Silver 1, Asc 1, Immortal 2, Radiant", placeholder="asc 1", required=True, max_length=32)
    async def on_submit(self, interaction: discord.Interaction):
        disp = normalize_rank(str(self.rank_input.value))
        if not disp:
            return await interaction.response.send_message("Format invalide. Ex: `Silver 1`, `Asc 1`, `Radiant`.", ephemeral=True)
        await apply_rank_role(interaction.guild, interaction.user, disp)
        await interaction.response.send_message(f"✅ Peak enregistré : **{disp}**", ephemeral=True)

class RankButtonView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎯 Déclarer mon peak ELO", style=discord.ButtonStyle.primary, custom_id="rank:open")
    async def open(self, interaction:discord.Interaction, button:discord.ui.Button):
        await interaction.response.send_modal(RankModal())

async def ensure_rank_prompt_in_autoroles(guild:discord.Guild, cat_welcome:discord.CategoryChannel):
    ch = find_text_by_slug(cat_welcome, "auto rôles") or find_text_by_slug(cat_welcome, "auto-roles")
    if not ch: return
    try:
        for m in await ch.pins():
            if m.author==guild.me and m.components:
                return
    except: pass
    async for m in ch.history(limit=25):
        if m.author==guild.me and m.components:
            return
    em = discord.Embed(title="🎯 Peak ELO — Valorant", description="Clique pour déclarer ton **peak ELO** et recevoir ton rôle.", color=0x5865F2)
    msg = await ch.send(embed=em, view=RankButtonView())
    try: await msg.pin()
    except: pass

# ===================== Roulette map + votes =====================
VALORANT_MAPS = [
    "Ascent","Bind","Haven","Split","Lotus","Sunset","Icebox","Breeze","Pearl","Fracture","Corrode","Abyss"
]

def map_image_url(name: str) -> str:
    # Placeholder lisible partout (remplace par tes liens d’images)
    return f"https://dummyimage.com/1280x640/111827/ffffff&text={name.replace(' ', '%20')}"

@dataclass
class MapVoteState:
    current: str
    voters: Dict[int, str] = field(default_factory=dict)  # user_id -> "yes" / "no"
    yes: int = 0
    no: int  = 0
    locked: bool = False  # true = acceptée

map_votes: Dict[int, MapVoteState] = {}
VOTE_THRESHOLD_ACCEPT = 5
VOTE_THRESHOLD_REJECT = 5

def roll_random_map(exclude: Optional[str] = None) -> str:
    pool = [m for m in VALORANT_MAPS if m != exclude] if exclude else VALORANT_MAPS
    return random.choice(pool) if pool else random.choice(VALORANT_MAPS)

def build_map_embed(set_idx: int, state: MapVoteState) -> discord.Embed:
    title = f"🗺️ Roulette map — Partie {set_idx}"
    desc  = (
        f"**Map proposée :** **{state.current}**\n\n"
        f"**Votes** — ✅ Oui: **{state.yes}/{VOTE_THRESHOLD_ACCEPT}** • ❌ Non: **{state.no}/{VOTE_THRESHOLD_REJECT}**\n"
        f"*(1 vote par personne)*"
    )
    color = 0x2ecc71 if state.locked else 0x5865F2
    em = discord.Embed(title=title, description=desc, color=color)
    em.set_image(url=map_image_url(state.current))
    em.set_footer(text="✅ Map acceptée" if state.locked else "Votez avec les boutons ci-dessous")
    return em

class MapVoteView(discord.ui.View):
    """Vue persistante : Oui / Non / Relancer (Orga)."""
    def __init__(self, set_idx: int):
        super().__init__(timeout=None)
        self.set_idx = set_idx

        b_yes    = discord.ui.Button(label="✅ Oui", style=discord.ButtonStyle.success,   custom_id=f"mapvote:yes:{set_idx}")
        b_no     = discord.ui.Button(label="❌ Non", style=discord.ButtonStyle.danger,    custom_id=f"mapvote:no:{set_idx}")
        b_reroll = discord.ui.Button(label="🎲 Relancer (Orga)", style=discord.ButtonStyle.secondary, custom_id=f"mapvote:reroll:{set_idx}")

        async def cb_yes(inter: discord.Interaction):
            state = map_votes.get(self.set_idx)
            if not state:
                state = map_votes[self.set_idx] = MapVoteState(current=roll_random_map())
            if state.locked:
                return await inter.response.send_message("La map est déjà acceptée.", ephemeral=True)
            uid = inter.user.id
            if uid in state.voters:
                return await inter.response.send_message("Tu as déjà voté.", ephemeral=True)
            state.voters[uid] = "yes"
            state.yes += 1
            if state.yes >= VOTE_THRESHOLD_ACCEPT:
                state.locked = True
            await inter.response.edit_message(embed=build_map_embed(self.set_idx, state), view=self)
            await inter.followup.send("Vote enregistré ✅", ephemeral=True)

        async def cb_no(inter: discord.Interaction):
            state = map_votes.get(self.set_idx)
            if not state:
                state = map_votes[self.set_idx] = MapVoteState(current=roll_random_map())
            if state.locked:
                return await inter.response.send_message("La map est déjà acceptée.", ephemeral=True)
            uid = inter.user.id
            if uid in state.voters:
                return await inter.response.send_message("Tu as déjà voté.", ephemeral=True)
            state.voters[uid] = "no"
            state.no += 1
            rerolled = False
            if state.no >= VOTE_THRESHOLD_REJECT:
                old = state.current
                state.current = roll_random_map(exclude=old)
                state.voters.clear(); state.yes = 0; state.no = 0; state.locked = False
                rerolled = True
            await inter.response.edit_message(embed=build_map_embed(self.set_idx, state), view=self)
            if rerolled:
                await inter.followup.send("❌ Refusé (5 non). 🎲 Nouvelle map proposée !", ephemeral=True)
            else:
                await inter.followup.send("Vote enregistré ❌", ephemeral=True)

        async def cb_reroll(inter: discord.Interaction):
            if not (inter.user.guild_permissions.administrator or any(r.name.lower()=="orga pp" for r in inter.user.roles)):
                return await inter.response.send_message("Réservé aux **Orga PP** / Admin.", ephemeral=True)
            state = map_votes.get(self.set_idx)
            if not state:
                state = map_votes[self.set_idx] = MapVoteState(current=roll_random_map())
            old = state.current
            state.current = roll_random_map(exclude=old)
            state.voters.clear(); state.yes = 0; state.no = 0; state.locked = False
            await inter.response.edit_message(embed=build_map_embed(self.set_idx, state), view=self)
            await inter.followup.send("🎲 Nouvelle map proposée.", ephemeral=True)

        b_yes.callback = cb_yes
        b_no.callback  = cb_no
        b_reroll.callback = cb_reroll
        self.add_item(b_yes); self.add_item(b_no); self.add_item(b_reroll)

async def ensure_mapvote_panel_once(chat: discord.TextChannel, set_idx: int):
    title = f"🗺️ Roulette map — Partie {set_idx}"
    try:
        for m in await chat.pins():
            if m.author == chat.guild.me and m.embeds and m.embeds[0].title == title:
                return
    except: pass
    async for m in chat.history(limit=30):
        if m.author == chat.guild.me and m.embeds and m.embeds[0].title == title:
            return
    map_votes[set_idx] = MapVoteState(current=roll_random_map())
    msg = await chat.send(embed=build_map_embed(set_idx, map_votes[set_idx]), view=MapVoteView(set_idx))
    try: await msg.pin()
    except: pass

# ===================== Voice creator (temp rooms) =====================
@dataclass
class TempRoom:
    owner_id: int
    voice_id: int
    text_id:  int
    private: bool = False
    limit:   int  = 0
    whitelist: Set[int] = field(default_factory=set)
    blacklist: Set[int] = field(default_factory=set)

temp_rooms: Dict[int, TempRoom] = {}        # voice_id -> TempRoom
delete_tasks: Dict[int, asyncio.Task] = {}  # voice_id -> task

def staff_or_owner(member: discord.Member, room: TempRoom) -> bool:
    if member.guild_permissions.administrator: return True
    low = {r.name.lower() for r in member.roles}
    return member.id == room.owner_id or "orga pp" in low

class VoiceControlView(discord.ui.View):
    def __init__(self, room: TempRoom):
        super().__init__(timeout=None)
        self.room = room

    async def _resolve(self, interaction: discord.Interaction) -> Tuple[Optional[discord.VoiceChannel], Optional[TempRoom]]:
        vc = interaction.guild.get_channel(self.room.voice_id)
        if not vc:
            await interaction.response.send_message("Salon introuvable.", ephemeral=True)
            return None, None
        return vc, temp_rooms.get(vc.id)

    @discord.ui.button(label="🔒 Rendre privé", style=discord.ButtonStyle.danger, custom_id="vc:private")
    async def make_private(self, interaction:discord.Interaction, _:discord.ui.Button):
        vc, room = await self._resolve(interaction)
        if not vc or not room: return
        if not staff_or_owner(interaction.user, room):
            return await interaction.response.send_message("Réservé au créateur/Orga PP.", ephemeral=True)
        overwrites = vc.overwrites
        overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(connect=False)
        await vc.edit(overwrites=overwrites, reason="VC private")
        room.private = True
        await interaction.response.send_message("Salon **privé**.", ephemeral=True)

    @discord.ui.button(label="🔓 Rendre public", style=discord.ButtonStyle.success, custom_id="vc:public")
    async def make_public(self, interaction:discord.Interaction, _:discord.ui.Button):
        vc, room = await self._resolve(interaction)
        if not vc or not room: return
        if not staff_or_owner(interaction.user, room):
            return await interaction.response.send_message("Réservé au créateur/Orga PP.", ephemeral=True)
        overwrites = vc.overwrites
        overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(connect=True)
        await vc.edit(overwrites=overwrites, reason="VC public")
        room.private = False
        await interaction.response.send_message("Salon **public**.", ephemeral=True)

    @discord.ui.button(label="👥 Limite", style=discord.ButtonStyle.secondary, custom_id="vc:limit")
    async def set_limit(self, interaction:discord.Interaction, _:discord.ui.Button):
        vc, room = await self._resolve(interaction)
        if not vc or not room: return
        if not staff_or_owner(interaction.user, room):
            return await interaction.response.send_message("Réservé au créateur/Orga PP.", ephemeral=True)
        class LimitModal(discord.ui.Modal, title="Fixer une limite (0 = illimité)"):
            value = discord.ui.TextInput(label="Nombre", placeholder="0..99", required=True, max_length=2)
            async def on_submit(self, inter: discord.Interaction):
                try:
                    n = int(str(self.value))
                    n = max(0, min(99, n))
                except:
                    return await inter.response.send_message("Nombre invalide.", ephemeral=True)
                try: await vc.edit(user_limit=n)
                except: pass
                room.limit = n
                await inter.response.send_message(f"Limite fixée à **{n}**.", ephemeral=True)
        await interaction.response.send_modal(LimitModal())

    @discord.ui.button(label="✅ Whitelist+", style=discord.ButtonStyle.success, custom_id="vc:wl_add")
    async def wl_add(self, interaction:discord.Interaction, _:discord.ui.Button):
        vc, room = await self._resolve(interaction)
        if not vc or not room: return
        if not staff_or_owner(interaction.user, room):
            return await interaction.response.send_message("Réservé au créateur/Orga PP.", ephemeral=True)
        class AddModal(discord.ui.Modal, title="Ajouter à la whitelist"):
            user = discord.ui.TextInput(label="ID ou @mention", required=True)
            async def on_submit(self, inter:discord.Interaction):
                m = re.findall(r"\d{15,20}", str(self.user))
                if not m:
                    return await inter.response.send_message("Utilisateur invalide.", ephemeral=True)
                room.whitelist.add(int(m[0]))
                await inter.response.send_message("Ajouté à la whitelist.", ephemeral=True)
        await interaction.response.send_modal(AddModal())

    @discord.ui.button(label="🗑️ Whitelist-", style=discord.ButtonStyle.secondary, custom_id="vc:wl_del")
    async def wl_del(self, interaction:discord.Interaction, _:discord.ui.Button):
        vc, room = await self._resolve(interaction)
        if not vc or not room: return
        if not staff_or_owner(interaction.user, room):
            return await interaction.response.send_message("Réservé au créateur/Orga PP.", ephemeral=True)
        class DelModal(discord.ui.Modal, title="Retirer de la whitelist"):
            user = discord.ui.TextInput(label="ID ou @mention", required=True)
            async def on_submit(self, inter:discord.Interaction):
                m = re.findall(r"\d{15,20}", str(self.user))
                if not m:
                    return await inter.response.send_message("Utilisateur invalide.", ephemeral=True)
                room.whitelist.discard(int(m[0]))
                await inter.response.send_message("Retiré de la whitelist.", ephemeral=True)
        await interaction.response.send_modal(DelModal())

    @discord.ui.button(label="⛔ Blacklist+", style=discord.ButtonStyle.danger, custom_id="vc:bl_add")
    async def bl_add(self, interaction:discord.Interaction, _:discord.ui.Button):
        vc, room = await self._resolve(interaction)
        if not vc or not room: return
        if not staff_or_owner(interaction.user, room):
            return await interaction.response.send_message("Réservé au créateur/Orga PP.", ephemeral=True)
        class AddModal(discord.ui.Modal, title="Ajouter à la blacklist"):
            user = discord.ui.TextInput(label="ID ou @mention", required=True)
            async def on_submit(self, inter:discord.Interaction):
                m = re.findall(r"\d{15,20}", str(self.user))
                if not m:
                    return await inter.response.send_message("Utilisateur invalide.", ephemeral=True)
                room.blacklist.add(int(m[0]))
                await inter.response.send_message("Ajouté à la blacklist.", ephemeral=True)
        await interaction.response.send_modal(AddModal())

    @discord.ui.button(label="🧹 Blacklist-", style=discord.ButtonStyle.secondary, custom_id="vc:bl_del")
    async def bl_del(self, interaction:discord.Interaction, _:discord.ui.Button):
        vc, room = await self._resolve(interaction)
        if not vc or not room: return
        if not staff_or_owner(interaction.user, room):
            return await interaction.response.send_message("Réservé au créateur/Orga PP.", ephemeral=True)
        class DelModal(discord.ui.Modal, title="Retirer de la blacklist"):
            user = discord.ui.TextInput(label="ID ou @mention", required=True)
            async def on_submit(self, inter:discord.Interaction):
                m = re.findall(r"\d{15,20}", str(self.user))
                if not m:
                    return await inter.response.send_message("Utilisateur invalide.", ephemeral=True)
                room.blacklist.discard(int(m[0]))
                await inter.response.send_message("Retiré de la blacklist.", ephemeral=True)
        await interaction.response.send_modal(DelModal())

    @discord.ui.button(label="📜 Voir listes", style=discord.ButtonStyle.secondary, custom_id="vc:lists")
    async def lists(self, interaction:discord.Interaction, _:discord.ui.Button):
        vc, room = await self._resolve(interaction)
        if not vc or not room: return
        wl = ", ".join(f"<@{u}>" for u in room.whitelist) or "—"
        bl = ", ".join(f"<@{u}>" for u in room.blacklist) or "—"
        await interaction.response.send_message(f"**Whitelist**: {wl}\n**Blacklist**: {bl}", ephemeral=True)

async def start_delete_timer(guild: discord.Guild, voice_id: int):
    await asyncio.sleep(TEMP_DELETE_GRACE_S)
    room = temp_rooms.get(voice_id)
    if not room: return
    vc = guild.get_channel(voice_id)
    if vc and len(vc.members) == 0:
        try:
            txt = guild.get_channel(room.text_id)
            if txt: await txt.delete()
        except: pass
        try: await vc.delete()
        except: pass
        temp_rooms.pop(voice_id, None)
        delete_tasks.pop(voice_id, None)

# ===================== Bot / Hooks / Events =====================
class FiveBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=INTENTS)
    async def setup_hook(self):
        # Vues persistantes
        for i in range(1, PREP_PAIRS+1):
            self.add_view(PanelView(i))
            self.add_view(MapVoteView(i))
        self.add_view(RankButtonView())
        # Sync tree
        if GUILD_ID:
            gid=int(GUILD_ID)
            self.tree.copy_global_to(guild=discord.Object(id=gid))
            await self.tree.sync(guild=discord.Object(id=gid))
        else:
            await self.tree.sync()

bot = FiveBot()

@bot.event
async def on_member_join(member: discord.Member):
    # pas de DM : ping vers auto-rôles
    try:
        cat=discord.utils.get(member.guild.categories, name=CAT_WELCOME_NAME)
        if cat:
            ch=find_text_by_slug(cat,"auto rôles") or find_text_by_slug(cat,"auto-roles")
            if ch and ch.permissions_for(member.guild.me).send_messages:
                await ch.send(f"{member.mention} 👉 Va dans **🪙・auto-rôles** et clique sur **🎯 Déclarer mon peak ELO**.")
    except: pass

@bot.event
async def on_voice_state_update(member:discord.Member, before:discord.VoiceState, after:discord.VoiceState):
    guild = member.guild
    # Création auto
    if after and after.channel and after.channel.name == CREATE_VOICE_NAME:
        cat = pp_category(guild) or after.channel.category
        vc = await guild.create_voice_channel(f"🎤 Salon de {member.display_name}", category=cat)
        txt = await guild.create_text_channel(f"🔧-controle-{member.name}".lower(), category=cat, overwrites={
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        })
        try: await member.move_to(vc)
        except: pass
        room = TempRoom(owner_id=member.id, voice_id=vc.id, text_id=txt.id)
        temp_rooms[vc.id] = room
        view = VoiceControlView(room)
        await txt.send(f"{member.mention}, voici les contrôles de **ton** salon :", view=view)

    # Timer suppression si vide
    if before and before.channel and before.channel.id in temp_rooms:
        vc = before.channel
        if len(vc.members) == 0:
            if vc.id in delete_tasks and not delete_tasks[vc.id].done():
                delete_tasks[vc.id].cancel()
            delete_tasks[vc.id] = asyncio.create_task(start_delete_timer(guild, vc.id))

    # WL/BL + privé
    if after and after.channel and after.channel.id in temp_rooms:
        room = temp_rooms[after.channel.id]
        if member.id in room.blacklist and not member.guild_permissions.administrator:
            try: await member.move_to(None)
            except: pass
        if room.private and member.id not in room.whitelist and member.id != room.owner_id and not member.guild_permissions.administrator:
            try: await member.move_to(None)
            except: pass

# ===================== Slash Commands =====================
@bot.tree.command(description="Configurer tout le serveur (sans doublons).")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup(inter:discord.Interaction):
    await inter.response.defer(ephemeral=True, thinking=True)
    g=inter.guild

    await ensure_roles(g)
    cat_welcome = await create_category_with_channels(g, CAT_WELCOME_NAME, WELCOME_CHANNELS)
    cat_commu   = await create_category_with_channels(g, CAT_COMMU_NAME,   COMMU_CHANNELS)
    cat_fun     = await create_category_with_channels(g, CAT_FUN_NAME,     [("🎭・conte-auteurs","text"), ("🎨・fan-art","text")])
    cat_pp      = await create_category_with_channels(g, CAT_PP_NAME,      PP_TEXT)

    # Créateur de salons
    if not discord.utils.find(lambda c: c.name==CREATE_VOICE_NAME, cat_pp.voice_channels):
        await g.create_voice_channel(CREATE_VOICE_NAME, category=cat_pp)

    # Vocs PP + textes • salon-partie-1..4
    await create_pp_voice_structure(g, cat_pp)
    await ensure_party_text_channels(g, cat_pp, count=PREP_PAIRS)

    # Panneaux : file 5v5 + roulette map (détection robuste des salons-partie)
    for i in range(1, PREP_PAIRS+1):
        chat = get_party_text_channel(g, i)
        if not chat:
            continue
        await ensure_panel_once(chat, panel_embed(g, i), PanelView(i))
        await ensure_mapvote_panel_once(chat, i)

    # Peak ELO dans auto-rôles
    await ensure_rank_prompt_in_autoroles(g, cat_welcome)

    # Branding
    try:
        bienv = find_text_by_slug(cat_welcome, "bienvenue")
        await g.edit(name=SERVER_BRAND_NAME, system_channel=bienv or g.system_channel)
    except: pass
    try:
        me=g.me
        if me and me.nick!=BOT_NICKNAME:
            await me.edit(nick=BOT_NICKNAME, reason="Brand nickname")
    except: pass

    # Règles (post & pin si pas déjà)
    try:
        reg1 = find_text_by_slug(cat_welcome,"règlement")
        if reg1: await post_server_rules(reg1)
        reg2 = find_text_by_slug(cat_pp,"règlement-pp")
        if reg2: await post_rules_pp(reg2)
    except: pass

    await inter.followup.send("✅ Setup terminé : panels 5v5 + roulette map dans `• salon-partie-1..4`, bouton peak ELO dans `🪙・auto-rôles`, créateur de salon vocal opérationnel.", ephemeral=True)

@bot.tree.command(description="Publier un party code dans le salon-partie choisi.")
@app_commands.describe(partie="1 à 4", code="Le party code", ping_here="Ping @here ? (oui/non)")
@app_commands.choices(partie=[app_commands.Choice(name=str(i), value=i) for i in range(1, PREP_PAIRS+1)])
async def party_code(inter:discord.Interaction, partie:app_commands.Choice[int], code:str, ping_here:Optional[str]="non"):
    roles = {r.name.lower() for r in inter.user.roles}
    if 'orga pp' not in roles and not inter.user.guild_permissions.administrator:
        return await inter.response.send_message("Commande réservée aux **Orga PP** / Admin.", ephemeral=True)
    cat = pp_category(inter.guild)
    if not cat: return await inter.response.send_message("Catégorie PP introuvable.", ephemeral=True)
    ch = get_party_text_channel(inter.guild, partie.value)
    if not ch: return await inter.response.send_message("salon-partie introuvable.", ephemeral=True)

    embed = discord.Embed(title=f"🎮 Party Code — Partie {partie.value}", description=f"**Code :** `{code}`\nSalon associé : **Préparation {partie.value}**", color=0x2ecc71)
    await ch.send(content="@here" if (ping_here or "").lower().startswith("o") else None, embed=embed)
    try: await ch.edit(topic=f"Party code actuel: {code} (partie {partie.value})")
    except: pass
    await inter.response.send_message(f"✅ Code posté dans {ch.mention}", ephemeral=True)

@bot.tree.command(description="(Re)poser la roulette map dans chaque salon-partie existant.")
@app_commands.checks.has_permissions(manage_guild=True)
async def map_seed(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    g = interaction.guild
    ok, miss = [], []
    for i in range(1, PREP_PAIRS + 1):
        chat = get_party_text_channel(g, i)
        if not chat:
            miss.append(i); 
            continue
        try:
            await ensure_mapvote_panel_once(chat, i)
            ok.append(i)
        except Exception:
            miss.append(i)
    text = []
    if ok:   text.append("✅ Roulette posée pour: " + ", ".join(map(str, ok)))
    if miss: text.append("⚠️ Introuvable: " + ", ".join(map(str, miss)) + " (crée les salons-partie manquants)")
    await interaction.followup.send("\n".join(text) or "Rien à faire.", ephemeral=True)

@bot.tree.command(description="Définir ton peak ELO (VALORANT).")
@app_commands.describe(valeur="Ex: 'silver 1', 'asc 1', 'immortal 2', 'radiant'")
async def set_rank(inter:discord.Interaction, valeur:str):
    disp = normalize_rank(valeur)
    if not disp:
        return await inter.response.send_message("Format invalide. Ex: `Silver 1`, `Asc 1`, `Radiant`.", ephemeral=True)
    await apply_rank_role(inter.guild, inter.user, disp)
    await inter.response.send_message(f"✅ Peak enregistré : **{disp}**", ephemeral=True)

@bot.tree.command(description="Voir le peak ELO d'un membre.")
@app_commands.describe(membre="Laisser vide pour toi-même.")
async def rank_show(inter:discord.Interaction, membre:Optional[discord.Member]=None):
    m=membre or inter.user
    best=None; bestv=-1
    for r in m.roles:
        if is_rank_role_name(r.name):
            v=rank_value(r.name)
            if v>bestv: best,bestv=r.name,v
    if best is None:
        return await inter.response.send_message(f"{m.mention} n'a pas encore de peak ELO.", ephemeral=True)
    await inter.response.send_message(f"Peak ELO de {m.mention} : **{best}**", ephemeral=True)

@bot.tree.command(description="Tirer une map au hasard (simple).")
async def roulette(inter:discord.Interaction):
    choice=random.choice(VALORANT_MAPS)
    await inter.response.send_message(f"🗺️ Map tirée au sort : **{choice}**")

# ===================== Run =====================
def main():
    if not TOKEN: raise RuntimeError("DISCORD_BOT_TOKEN manquant (.env)")
    # (optionnel) keep_alive si tu utilises un ping HTTP externe
    try:
        from keep_alive import keep_alive
        keep_alive()
    except Exception as e:
        print(f"[keep_alive] disabled: {e}")
    bot.run(TOKEN)

if __name__ == "__main__":
    main()
