#!/usr/bin/env python3
"""
Bot de veille - Air France Recrutement
Scanne toutes les offres toutes les 5 minutes et t'envoie une notification
sur ton téléphone (via l'app gratuite ntfy) dès qu'une offre correspond
à un mot-clé (PCB, personnel complémentaire de bord, vivier, été 2027...).
Tant que rien ne correspond : aucune notif, il continue de scanner.

Aucune bibliothèque à installer : Python 3 suffit.
Lancement :  python3 bot_pcb_airfrance.py
Arrêt :      Ctrl + C
"""

import json
import os
import re
import sys
import time
import html
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime

# ====================== RÉGLAGES ======================

# 1) Choisis un nom de canal unique et difficile à deviner,
#    puis abonne-toi au même nom dans l'app ntfy sur ton téléphone.
NTFY_TOPIC = "louis-af-pcb-CHANGE-MOI-123"

INTERVALLE_MINUTES = 5

# Mots-clés recherchés (majuscules/accents ignorés).
# Une offre est signalée si son titre OU son lien contient l'un d'eux.
MOTS_CLES = [
    "personnel complementaire de bord",
    "complementaire de bord",
    "pcb",
    "vivier",
    "ete 2027",
    "saison 2027",
    "saisonnier",
    "hotesse",
    "steward",
    "pnc",
    "personnel navigant commercial",
    "navigant commercial",
    "cabin crew",
]

URL_LISTE = "https://recrutement.airfrance.com/offre-de-emploi/liste-toutes-offres.aspx"
PAGES_MAX = 20
FICHIER_DEJA_VUES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offres_deja_signalees.json")

# =======================================================

ENTETES = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

LIEN_OFFRE = re.compile(
    r'<a\b([^>]*?)href="([^"]*?emploi-[^"]*?_(\d+)\.aspx[^"]*)"([^>]*)>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
ATTR_TITLE = re.compile(r'title="([^"]*)"', re.IGNORECASE)
BALISES = re.compile(r"<[^>]+>")


def log(msg):
    print(f"[{datetime.now():%d/%m %H:%M:%S}] {msg}", flush=True)


def normaliser(texte):
    """minuscules, sans accents, ponctuation -> espaces."""
    texte = unicodedata.normalize("NFD", texte.lower())
    texte = "".join(c for c in texte if unicodedata.category(c) != "Mn")
    return " " + re.sub(r"[^a-z0-9]+", " ", texte).strip() + " "


MOTS_CLES_NORM = [normaliser(m) for m in MOTS_CLES]


def correspond(texte):
    t = normaliser(texte)
    return [m.strip() for m in MOTS_CLES_NORM if m in t]


def telecharger(url):
    req = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def extraire_offres(page_html):
    offres = {}
    for avant, href, oid, apres, texte in LIEN_OFFRE.findall(page_html):
        titre = html.unescape(BALISES.sub(" ", texte)).strip()
        m = ATTR_TITLE.search(avant + apres)
        info = html.unescape(m.group(1)) if m else ""
        lien = html.unescape(href)
        if lien.startswith("/"):
            lien = "https://recrutement.airfrance.com" + lien
        elif not lien.startswith("http"):
            lien = "https://recrutement.airfrance.com/offre-de-emploi/" + lien
        if oid not in offres or (titre and not offres[oid]["titre"]):
            offres[oid] = {"id": oid, "titre": titre, "info": info, "lien": lien}
    return offres


def scanner_tout():
    toutes = {}
    for page in range(1, PAGES_MAX + 1):
        url = f"{URL_LISTE}?LCID=1036&page={page}"
        offres = extraire_offres(telecharger(url))
        nouvelles = {k: v for k, v in offres.items() if k not in toutes}
        if not nouvelles:
            break
        toutes.update(nouvelles)
        time.sleep(1)  # politesse envers le site
    return toutes


def notifier(titre, message, lien=None, urgent=True):
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    headers = {"Title": titre.encode("ascii", "ignore").decode(), "Tags": "airplane"}
    if urgent:
        headers["Priority"] = "urgent"
    if lien:
        headers["Click"] = lien
    req = urllib.request.Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        log(f"Échec de la notification : {e}")


def charger_deja_vues():
    try:
        with open(FICHIER_DEJA_VUES, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def sauver_deja_vues(ids):
    with open(FICHIER_DEJA_VUES, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f)


def scan_unique():
    """Un seul passage (utilisé par GitHub Actions, lancé toutes les 5 min)."""
    deja_vues = charger_deja_vues()
    offres = scanner_tout()
    if not offres:
        raise RuntimeError("aucune offre lue (structure du site modifiée ?)")
    for o in offres.values():
        mots = correspond(f"{o['titre']} {o['info']} {o['lien']}")
        if mots and o["id"] not in deja_vues:
            log(f"TROUVÉ : {o['titre']} -> {o['lien']}")
            notifier("OFFRE AIR FRANCE TROUVEE !",
                     f"{o['titre']}\nMots-cles : {', '.join(mots)}\n{o['lien']}", lien=o["lien"])
            deja_vues.add(o["id"])
    sauver_deja_vues(deja_vues)
    log(f"{len(offres)} offres scannées.")


def main():
    global NTFY_TOPIC
    NTFY_TOPIC = os.environ.get("NTFY_TOPIC", NTFY_TOPIC)
    if "CHANGE-MOI" in NTFY_TOPIC:
        print("Modifie d'abord NTFY_TOPIC en haut du fichier (nom de canal unique).")
        sys.exit(1)

    if "--once" in sys.argv:
        scan_unique()
        return

    deja_vues = charger_deja_vues()
    notifier("Bot Air France lance", "Veille PCB active. Scan toutes les "
             f"{INTERVALLE_MINUTES} min. Tu seras prevenu des qu'une offre apparait.", urgent=False)
    log(f"Bot lancé — {len(MOTS_CLES)} mots-clés, scan toutes les {INTERVALLE_MINUTES} min.")

    echecs = 0
    while True:
        try:
            offres = scanner_tout()
            if not offres:
                raise RuntimeError("aucune offre lue (structure du site modifiée ?)")
            echecs = 0
            trouvees = 0
            for o in offres.values():
                mots = correspond(f"{o['titre']} {o['info']} {o['lien']}")
                if mots and o["id"] not in deja_vues:
                    trouvees += 1
                    log(f"✈️  TROUVÉ : {o['titre']} ({', '.join(mots)}) -> {o['lien']}")
                    notifier("OFFRE AIR FRANCE TROUVEE !",
                             f"{o['titre']}\nMots-cles : {', '.join(mots)}\n{o['lien']}",
                             lien=o["lien"])
                    deja_vues.add(o["id"])
                    sauver_deja_vues(deja_vues)
            log(f"{len(offres)} offres scannées — {trouvees} nouvelle(s) correspondance(s).")
        except (urllib.error.URLError, RuntimeError, TimeoutError, OSError) as e:
            echecs += 1
            log(f"Erreur : {e}")
            if echecs == 6:  # ~30 min d'échecs d'affilée
                notifier("Bot Air France en panne", f"6 echecs d'affilee : {e}", urgent=False)
        time.sleep(INTERVALLE_MINUTES * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Bot arrêté.")
