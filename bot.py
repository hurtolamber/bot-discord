# bot.py
import os
import random
import asyncio
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ------------------ Config ------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True          # active aussi "Server Members Intent" dans le dev portal
INTENTS.messages = True
INTENTS.message_content = False
INTENTS.voice_states = True

PREP_PAIRS = 4                  # 4 sets (parties perso)
PREP_VOICE_LIMIT = 10           # “Préparation i”
SIDE_VOICE_LIMIT  = 5           # “⚔ · Attaque” / “🛡 · Défense”

# DA / noms
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

ATTACK_KEYWORD  = "attaque"
DEFENSE_KEYWORD = "défense"

# ------------------ Ranks ------------------
TIERS = [
    ("iron","Iron",3), ("bronze","Bronze",3), ("silver","Silver",3),
    ("gold","Gold",3), ("platinum","Platinum",3), ("diamond","Diamond",3),
    ("ascendant","Ascendant",3), ("immortal","Immortal",3), ("radiant","Radiant",1),
]
TIER_INDEX = {k:i for i,(k,_,_) in enumerate(TIERS)}
TIER_META  = {k:(label,divs) for k,(label,divs) in {k:(L,d) for k,L,d in TIERS}.items()}
TIER_ALIASES = {
    "argent":"silver","or":"gold","platine":"platinum","diamant":"diamond",
    "plat":"platinum","dia":"diamond","asc":"ascendant","imm":"immortal","imo":"immortal",
    "rad":"radiant","gld":"gold","silv":"silver","bron":"bronze","unrank":"iron",
}
ROMAN={"i":1,"ii":2,"iii":3}
ROLE_COLORS={"Iron":0x7A7A7A,"Bronze":0x8C5A3C,"Silver":0xA7B4C0,"Gold":0xD4AF37,"Platinum":0x47C1B2,"Diamond":0x5EC1FF,"Ascendant":0x6AD16A,"Immortal":0xB45FFF,"Radiant":0xFFF26B}

def normalize_rank(t:str)->Optional[str]:
    if not t: return None
    s=t.strip().lower().replace("-"," ").replace("_"," ")
    parts=[p for p in s.split() if p]
    if not parts: return None
    tier=TIER_ALIASES.get(parts[0],parts[0])
    if tier not in TIER_INDEX: return None
    label,divs=TIER_META[tier]
    div=None
    if divs>1 and len(parts)>=2:
        p=parts[1]
        div=int(p) if p.isdigit() else ROMAN.get(p)
    if divs==1: return label
    if div is None: div=1
    div=max(1,min(divs,div))
    return f"{label} {div}"

def rank_value(display:str)->int:
    if not display: return 0
    s=display.lower()
    for key,(label,divs) in TIER_META.items():
        if label.lower() in s:
            ti=TIER_INDEX[key]
            if divs==1: d=divs
            else:
                d=1
                for tok in s.split():
                    if tok.isdigit(): d=int(tok)
                d=max(1,min(divs,d))
            return ti*100+int((d/divs)*100)
    return 0

def is_rank_role_name(name:str)->bool:
    labels=[L for _,L,_ in TIERS]
    return any(L.lower() in name.lower() for L in labels)

async def apply_rank_role(guild:discord.Guild, member:discord.Member, display:str):
    for r in list(member.roles):
        if is_rank_role_name(r.name):
            try: await member.remove_roles(r, reason="Update peak rank")
            except discord.Forbidden: pass
    base=display.split()[0]
    color=discord.Color(ROLE_COLORS.get(base,0x5865F2))
    role=discord.utils.get(guild.roles,name=display)
    if role is None:
        role=await guild.create_role(name=display,color=color,reason="Create rank role")
    await member.add_roles(role, reason="Set peak rank")

# ------------------ Utils chan/slug ------------------
def slug(s:str)->str:
    for sep in ["・","｜","|","—","-","•","·"]:
        s=s.replace(sep," ")
    return " ".join(s.lower().split())

def find_text_by_slug(cat:discord.CategoryChannel, target:str):
    t=target.lower()
    for ch in cat.text_channels:
        if t in slug(ch.name): return ch
    return None

def pp_category(guild:discord.Guild)->Optional[discord.CategoryChannel]:
    return discord.utils.get(guild.categories, name=CAT_PP_NAME)

def find_group_channels_for_set(guild:discord.Guild, i:int)->Tuple[Optional[discord.VoiceChannel],Optional[discord.VoiceChannel],Optional[discord.VoiceChannel]]:
    cat=pp_category(guild)
    if not cat: return None,None,None
    vcs=sorted(cat.voice_channels,key=lambda c:c.position)
    prep_name=f"Préparation {i}"
    prep=next((vc for vc in vcs if slug(vc.name)==slug(prep_name)),None)
    if not prep: return None,None,None
    atk=defn=None
    for vc in vcs:
        if vc.position<=prep.position: continue
        n=slug(vc.name)
        if atk is None and ATTACK_KEYWORD in n: atk=vc; continue
        if defn is None and DEFENSE_KEYWORD in n: defn=vc; continue
        if atk and defn: break
    return prep,atk,defn

async def create_category_with_channels(guild:discord.Guild, name:str, items:List[tuple])->discord.CategoryChannel:
    cat=discord.utils.get(guild.categories, name=name)
    if cat is None:
        cat=await guild.create_category(name,reason="Setup 5v5 bot")
    exist_text={c.name for c in cat.text_channels}
    exist_voice={c.name for c in cat.voice_channels}
    for nm,kind in items:
        if kind=="text" and nm not in exist_text:
            await guild.create_text_channel(nm, category=cat)
        elif kind=="voice" and nm not in exist_voice:
            await guild.create_voice_channel(nm, category=cat)
    return cat

async def ensure_party_text_channels(guild:discord.Guild, cat:discord.CategoryChannel, count:int=4):
    existing={slug(c.name):c for c in cat.text_channels}
    for i in range(1,count+1):
        s=f"salon partie {i}"
        if s not in existing:
            await guild.create_text_channel(f"• salon-partie-{i}", category=cat, reason="PP party text")

async def create_pp_voice_structure(guild:discord.Guild, cat:discord.CategoryChannel):
    """Crée/renomme Préparation i + ⚔/🛡 et applique les limites."""
    # Préparations
    for i in range(1, PREP_PAIRS+1):
        prep_name=f"Préparation {i}"
        prep=discord.utils.find(lambda vc: slug(vc.name)==slug(prep_name), cat.voice_channels)
        if not prep:
            prep=await guild.create_voice_channel(prep_name, category=cat, user_limit=PREP_VOICE_LIMIT)
        else:
            try: await prep.edit(user_limit=PREP_VOICE_LIMIT, reason="Apply PREP_VOICE_LIMIT")
            except discord.Forbidden: pass

        # blocs Attaque/Défense
        _, atk, defn = find_group_channels_for_set(guild, i)
        if not atk:
            atk = await guild.create_voice_channel("⚔ · Attaque", category=cat, user_limit=SIDE_VOICE_LIMIT)
        else:
            # rename si pas d’emoji
            if slug(atk.name)!=slug("⚔ · Attaque"):
                try: await atk.edit(name="⚔ · Attaque")
                except discord.Forbidden: pass
            try: await atk.edit(user_limit=SIDE_VOICE_LIMIT)
            except discord.Forbidden: pass

        if not defn:
            defn = await guild.create_voice_channel("🛡 · Défense", category=cat, user_limit=SIDE_VOICE_LIMIT)
        else:
            if slug(defn.name)!=slug("🛡 · Défense"):
                try: await defn.edit(name="🛡 · Défense")
                except discord.Forbidden: pass
            try: await defn.edit(user_limit=SIDE_VOICE_LIMIT)
            except discord.Forbidden: pass

async def apply_pp_limits(guild:discord.Guild, cat:discord.CategoryChannel, prep:int, side:int):
    for vc in cat.voice_channels:
        n=slug(vc.name)
        try:
            if n.startswith("préparation ") and ATTACK_KEYWORD not in n and DEFENSE_KEYWORD not in n:
                await vc.edit(user_limit=prep)
            elif ATTACK_KEYWORD in n or DEFENSE_KEYWORD in n:
                await vc.edit(user_limit=side)
        except discord.Forbidden: pass

# ------------------ Rôles clés ------------------
async def ensure_roles(guild:discord.Guild)->Dict[str,discord.Role]:
    existing={r.name:r for r in guild.roles}
    perms_admin=discord.Permissions(administrator=True)
    perms_orga =discord.Permissions(move_members=True, mute_members=True, deafen_members=True)
    perms_none =discord.Permissions.none()
    desired={
        "Admin":perms_admin,"Orga PP":perms_orga,"Staff":perms_none,"Joueur":perms_none,
        "Spectateur":perms_none,"Équipe Attaque":perms_none,"Équipe Défense":perms_none
    }
    out={}
    for name,perms in desired.items():
        role=existing.get(name)
        if role is None:
            role=await guild.create_role(name=name,permissions=perms,reason="Setup roles")
        else:
            try:
                if role.permissions!=perms:
                    await role.edit(permissions=perms,reason="Update role perms")
            except discord.Forbidden: pass
        key={"Admin":"admin","Orga PP":"orga","Staff":"staff","Joueur":"joueur","Spectateur":"spectateur","Équipe Attaque":"team_a","Équipe Défense":"team_b"}[name]
        out[key]=role
    return out

# ------------------ Files & panneaux ------------------
class SetQueues:
    def __init__(self): self.queues:Dict[int,List[int]]=defaultdict(list)
    def join(self,i:int,uid:int)->bool:
        q=self.queues[i]; 
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

set_queues=SetQueues()

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
        pins=await chat.pins()
        for m in pins:
            if m.author==chat.guild.me and m.embeds and m.embeds[0].title==embed.title:
                return
    except Exception: pass
    async for m in chat.history(limit=25):
        if m.author==chat.guild.me and m.embeds and m.embeds[0].title==embed.title:
            return
    msg=await chat.send(embed=embed, view=view)
    try: await msg.pin()
    except Exception: pass

class PanelView(discord.ui.View):
    def __init__(self,set_idx:int):
        super().__init__(timeout=None); self.set_idx=set_idx
        b_join  =discord.ui.Button(label="✅ Rejoindre",style=discord.ButtonStyle.success,   custom_id=f"panel:join:{set_idx}")
        b_leave =discord.ui.Button(label="🚪 Quitter",  style=discord.ButtonStyle.secondary, custom_id=f"panel:leave:{set_idx}")
        b_start =discord.ui.Button(label="🚀 Lancer la partie",style=discord.ButtonStyle.primary, custom_id=f"panel:start:{set_idx}")
        b_end   =discord.ui.Button(label="🧹 Finir la partie", style=discord.ButtonStyle.danger,  custom_id=f"panel:end:{set_idx}")

        async def cb_join(inter:discord.Interaction):
            if not set_queues.join(self.set_idx, inter.user.id):
                return await inter.response.send_message("Tu es déjà dans la file.", ephemeral=True)
            await inter.response.send_message(f"Tu as rejoint la file (Préparation {self.set_idx}).", ephemeral=True)
            try: await inter.message.edit(embed=panel_embed(inter.guild,self.set_idx), view=self)
            except Exception: pass

        async def cb_leave(inter:discord.Interaction):
            if not set_queues.leave(self.set_idx, inter.user.id):
                return await inter.response.send_message("Tu n'es pas dans la file.", ephemeral=True)
            await inter.response.send_message("Tu as quitté la file.", ephemeral=True)
            try: await inter.message.edit(embed=panel_embed(inter.guild,self.set_idx), view=self)
            except Exception: pass

        async def cb_start(inter:discord.Interaction):
            rn={r.name.lower() for r in inter.user.roles}
            if 'orga pp' not in rn and not inter.user.guild_permissions.administrator:
                return await inter.response.send_message("Orga PP requis.", ephemeral=True)
            await inter.response.defer(ephemeral=True)
            if not set_queues.ready(self.set_idx):
                need=10-len(set_queues.list(self.set_idx))
                return await inter.followup.send(f"Il manque **{need}** joueurs.", ephemeral=True)
            guild=inter.guild
            ids=set_queues.pop10(self.set_idx)
            members=[guild.get_member(u) for u in ids if guild.get_member(u)]
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
            roles=await ensure_roles(guild); roleA,roleB=roles["team_a"],roles["team_b"]
            _, atk, defn = find_group_channels_for_set(guild, self.set_idx)
            for m in A:
                try: await m.add_roles(roleA); 
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
            rn={r.name.lower() for r in inter.user.roles}
            if 'orga pp' not in rn and not inter.user.guild_permissions.administrator:
                return await inter.response.send_message("Orga PP requis.", ephemeral=True)
            await inter.response.defer(ephemeral=True)
            guild=inter.guild; roles=await ensure_roles(guild)
            removed=0
            for m in guild.members:
                if roles["team_a"] in m.roles or roles["team_b"] in m.roles:
                    try:
                        await m.remove_roles(roles["team_a"], roles["team_b"], reason="Match terminé")
                        removed+=1
                    except: pass
            set_queues.queues[self.set_idx]=[]
            await inter.followup.send(f"Rôles retirés de **{removed}** membres. File réinitialisée.")
            try: await inter.message.edit(embed=panel_embed(guild,self.set_idx), view=self)
            except: pass

        b_join.callback=cb_join; b_leave.callback=cb_leave; b_start.callback=cb_start; b_end.callback=cb_end
        self.add_item(b_join); self.add_item(b_leave); self.add_item(b_start); self.add_item(b_end)

# ------------------ Embeds textes ------------------
SERVER_RULES_TEXT = """**RÈGLEMENT DU SERVEUR — ARÈNE DE KAER MORHEN**
(…résumé…)
Le détail des règles PP est dans `📜・règlement-pp`. Bon jeu 🐺 !
"""

PP_RULES_TEXT = """**RÈGLEMENT PARTIES PERSO — VALORANT**
(…résumé fair-play, pas de triche, vocal, party code, sanctions…)
"""

async def post_server_rules(ch:discord.TextChannel):
    try:
        msg=await ch.send(SERVER_RULES_TEXT)
        try: await msg.pin()
        except: pass
    except: pass

async def post_rules_pp(ch:discord.TextChannel):
    try:
        msg=await ch.send(PP_RULES_TEXT)
        try: await msg.pin()
        except: pass
    except: pass

# ----------- UI Peak ELO (dans auto-rôles) -----------
class RankModal(discord.ui.Modal, title="Déclare ton peak ELO (VALORANT)"):
    rank_input = discord.ui.TextInput(
        label="Ex: Silver 1, Asc 1, Immortal 2, Radiant",
        placeholder="asc 1",
        required=True, max_length=32
    )
    async def on_submit(self, interaction: discord.Interaction):
        display=normalize_rank(str(self.rank_input.value))
        if not display:
            return await interaction.response.send_message("Format invalide. Ex: `Silver 1`, `Asc 1`, `Radiant`.", ephemeral=True)
        await apply_rank_role(interaction.guild, interaction.user, display)
        await interaction.response.send_message(f"✅ Peak enregistré : **{display}**", ephemeral=True)

class RankButtonView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎯 Déclarer mon peak ELO", style=discord.ButtonStyle.primary, custom_id="rank:open")
    async def open(self, interaction:discord.Interaction, _:discord.ui.Button):
        await interaction.response.send_modal(RankModal())

async def ensure_rank_prompt_in_autoroles(guild:discord.Guild, cat_welcome:discord.CategoryChannel):
    ch=find_text_by_slug(cat_welcome,"auto rôles") or find_text_by_slug(cat_welcome,"auto-roles")
    if not ch: return
    # évite les doublons
    try:
        for m in await ch.pins():
            if m.author==guild.me and m.components:
                return
    except: pass
    async for m in ch.history(limit=20):
        if m.author==guild.me and m.components:
            return
    em=discord.Embed(title="🎯 Peak ELO — Valorant", description="Clique pour déclarer ton **peak ELO** et recevoir ton rôle.", color=0x5865F2)
    msg=await ch.send(embed=em, view=RankButtonView())
    try: await msg.pin()
    except: pass

# ------------------ Bot ------------------
class FiveBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!", intents=INTENTS)
    async def setup_hook(self):
        # vues persistantes
        for i in range(1, PREP_PAIRS+1): self.add_view(PanelView(i))
        self.add_view(RankButtonView())
        if GUILD_ID:
            gid=int(GUILD_ID)
            self.tree.copy_global_to(guild=discord.Object(id=gid))
            await self.tree.sync(guild=discord.Object(id=gid))
        else:
            await self.tree.sync()

bot=FiveBot()

# ------------------ Events ------------------
@bot.event
async def on_member_join(member:discord.Member):
    # plus de DM : on laisse l’embed auto-rôles s’occuper du peak
    try:
        # petit embed bienvenue si tu veux
        cat=discord.utils.get(member.guild.categories, name=CAT_WELCOME_NAME)
        if cat:
            ch=find_text_by_slug(cat,"bienvenue")
            if ch and ch.permissions_for(member.guild.me).send_messages:
                await ch.send(f"Bienvenue {member.mention} ! Va dans **🪙・auto-rôles** pour déclarer ton peak ELO.")
    except: pass

# ------------------ Slash Commands ------------------
@bot.tree.command(description="Configurer les rôles, catégories, vocs, panneaux et auto-rôles (sans doublons).")
@app_commands.checks.has_permissions(manage_guild=True)
async def setup(inter:discord.Interaction):
    await inter.response.defer(ephemeral=True, thinking=True)
    g=inter.guild

    await ensure_roles(g)

    cat_welcome = await create_category_with_channels(g, CAT_WELCOME_NAME, WELCOME_CHANNELS)
    cat_commu   = await create_category_with_channels(g, CAT_COMMU_NAME,   COMMU_CHANNELS)
    cat_fun     = await create_category_with_channels(g, CAT_FUN_NAME,     [("🎭・conte-auteurs","text"),("🎨・fan-art","text")])
    cat_pp      = await create_category_with_channels(g, CAT_PP_NAME,      PP_TEXT)

    await create_pp_voice_structure(g, cat_pp)
    await ensure_party_text_channels(g, cat_pp, count=4)
    await apply_pp_limits(g, cat_pp, PREP_VOICE_LIMIT, SIDE_VOICE_LIMIT)

    # Panneaux dans • salon-partie-i
    for i in range(1, PREP_PAIRS+1):
        chat = None
        for ch in cat_pp.text_channels:
            if slug(ch.name)==slug(f"• salon-partie-{i}"): chat=ch; break
            if slug(ch.name)==slug(f"salon-partie-{i}"):   chat=ch; break
        if chat:
            await ensure_panel_once(chat, panel_embed(g,i), PanelView(i))

    # auto-rôles : bouton peak elo
    await ensure_rank_prompt_in_autoroles(g, cat_welcome)

    # branding
    try:
        bienv=find_text_by_slug(cat_welcome,"bienvenue")
        await g.edit(name=SERVER_BRAND_NAME, system_channel=bienv or g.system_channel)
    except: pass
    try:
        me=g.me
        if me and me.nick!=BOT_NICKNAME:
            await me.edit(nick=BOT_NICKNAME, reason="Brand nickname")
    except: pass

    # règles
    try:
        regles=find_text_by_slug(cat_welcome,"règlement")
        if regles: await post_server_rules(regles)
        regpp=find_text_by_slug(cat_pp,"règlement-pp")
        if regpp: await post_rules_pp(regpp)
    except: pass

    await inter.followup.send("✅ Setup terminé : vocs (avec emojis), panneaux dans **• salon-partie-1..4**, bouton peak ELO dans **🪙・auto-rôles**.", ephemeral=True)

@bot.tree.command(description="Publier un party code dans le salon-partie choisi.")
@app_commands.describe(partie="1 à 4", code="Le party code", ping_here="Ping @here ? (oui/non)")
@app_commands.choices(partie=[app_commands.Choice(name=str(i), value=i) for i in range(1,5)])
async def party_code(inter:discord.Interaction, partie:app_commands.Choice[int], code:str, ping_here:Optional[str]="non"):
    rn={r.name.lower() for r in inter.user.roles}
    if 'orga pp' not in rn and not inter.user.guild_permissions.administrator:
        return await inter.response.send_message("Commande réservée aux **Orga PP** / Admin.", ephemeral=True)
    cat=pp_category(inter.guild)
    if not cat: return await inter.response.send_message("Catégorie PP introuvable.", ephemeral=True)
    ch=None
    for t in cat.text_channels:
        if slug(t.name)==slug(f"• salon-partie-{partie.value}") or slug(t.name)==slug(f"salon-partie-{partie.value}"):
            ch=t; break
    if not ch: return await inter.response.send_message("salon-partie introuvable.", ephemeral=True)

    embed=discord.Embed(title=f"🎮 Party Code — Partie {partie.value}", description=f"**Code :** `{code}`\nSalon associé : **Préparation {partie.value}**", color=0x2ecc71)
    await ch.send(content="@here" if (ping_here or "").lower().startswith("o") else None, embed=embed)
    try: await ch.edit(topic=f"Party code actuel: {code} (partie {partie.value})")
    except: pass
    await inter.response.send_message(f"✅ Code posté dans {ch.mention}", ephemeral=True)

@bot.tree.command(description="Définir ton peak ELO (VALORANT).")
@app_commands.describe(valeur="Ex: 'silver 1', 'asc 1', 'immortal 2', 'radiant'")
async def set_rank(inter:discord.Interaction, valeur:str):
    disp=normalize_rank(valeur)
    if not disp:
        return await inter.response.send_message("Format invalide. Ex: `Silver 1`, `Asc 1`, `Radiant`.", ephemeral=True)
    await apply_rank_role(inter.guild, inter.user, disp)
    await inter.response.send_message(f"✅ Peak enregistré : **{disp}**", ephemeral=True)

@bot.tree.command(description="Voir le peak ELO d'un membre (via son rôle).")
@app_commands.describe(membre="Laisser vide pour toi-même.")
async def rank_show(inter:discord.Interaction, membre:Optional[discord.Member]=None):
    m=membre or inter.user
    best=None; bestv=-1
    for r in m.roles:
        if is_rank_role_name(r.name):
            v=rank_value(r.name)
            if v>bestv: best, bestv = r.name, v
    if best is None:
        return await inter.response.send_message(f"{m.mention} n'a pas encore de peak ELO.", ephemeral=True)
    await inter.response.send_message(f"Peak ELO de {m.mention} : **{best}**", ephemeral=True)

@bot.tree.command(description="Tirer une map aléatoire.")
async def roulette(inter:discord.Interaction):
    choice=random.choice(["Ascent","Bind","Haven","Split","Lotus","Sunset","Icebox","Breeze","Pearl","Fracture","Corrode","Abyss"])
    await inter.response.send_message(f"🗺️ Map tirée au sort : **{choice}**")

# ------------------ Run ------------------
def main():
    if not TOKEN: raise RuntimeError("DISCORD_BOT_TOKEN manquant.")
    try:
        from keep_alive import keep_alive
        keep_alive()
    except Exception as e:
        print(f"[keep_alive] disabled: {e}")
    bot.run(TOKEN)

if __name__=="__main__":
    main()
