


Fonctions principales :
- `/setup` : crée les **rôles**, **catégories** et **salons** (texte + vocaux de préparation).
- Bouton **Auto‑rôle** pour que les membres prennent le rôle *Joueur*.
- File d'attente 5v5 : `/join`, `/leave`, `/queue_show`.
- Lancement de match : `/start_match` forme 2 équipes (aléatoire), attribue les rôles Équipe A/B et déplace les joueurs connectés dans les salons de **Préparation X – Attaque/Défense**.
- Fin de match : `/end_match` enlève les rôles d'équipe.
- Utilitaires : `/code` pour le party code ; `/roulette` (tirage de map).

## Installation

1. **Créer un bot** sur https://discord.com/developers/applications
   - Dans *Bot* > Active **PRESENCE INTENT**, **SERVER MEMBERS INTENT** et **MESSAGE CONTENT** (facultatif ici).
   - Clique *Reset Token* pour obtenir le **TOKEN**.
2. **Inviter le bot** : dans *OAuth2 > URL Generator*, coche `applications.commands` et `bot` avec permissions :
   - Manage Roles, Manage Channels, Move Members, Send Messages, Use Slash Commands, View Channels.
3. **Configurer** le projet en local :
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # sous Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.template .env
   # colle ton DISCORD_BOT_TOKEN dans .env
   python bot.py
   ```

> Astuce : si tu mets `DISCORD_GUILD_ID` dans le `.env`, les slash‑commands se synchronisent plus vite pour ce serveur.

## Personnalisation rapide
- Modifie `PREP_PAIRS` pour le nombre de paires de salons vocaux.
- Edite les listes `WELCOME_CHANNELS`, `COMMU_CHANNELS`, `PP_TEXT` pour changer les noms.
- Change `ROLE_NAMES` si tu veux d'autres libellés (couleurs/permissions à gérer ensuite côté Discord).

## Notes
- Le bot a besoin de **Manage Roles** pour attribuer/retirer les rôles d'équipe et **Move Members** pour déplacer en vocal.
- La formation des équipes est **aléatoire**. Pour un équilibrage MMR, il faudra ajouter une base de données/notes par joueur.
