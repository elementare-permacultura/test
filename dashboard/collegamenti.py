"""Collegamenti automatici tra sessioni e gruppi automatici (solo libreria standard).

Ogni arco: {"id", "da", "a", "tipo", "confidenza", "prova", "fonte"}.
  confidenza: "certo" (dato esplicito), "probabile" (indizio forte), "proposta" (da confermare),
              "confermato"/"manuale" (decisione dell'utente).
Il verso dell'arco va dal più vecchio (o dal genitore) al più recente (o al figlio).
"""
import hashlib
import re
from datetime import datetime

# --- campi derivati -------------------------------------------------------------------------

RE_SESSIONE = re.compile(r"\bsession_[A-Za-z0-9]{8,}\b")
RE_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
RE_PR = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)")
RE_PR_BREVE = re.compile(r"\b([\w.-]+)/([\w.-]+)#(\d+)\b")
MAX_RIFERIMENTI = 20


def normalizza_cartella(percorso):
    p = (percorso or "").strip()
    if p.lower().startswith("repo "):
        p = p[5:].strip()
    return p.replace("\\", "/").rstrip("/").lower()


def chiave_cartella(percorso):
    """Impronta breve del percorso: uguale su macchine diverse se il percorso è lo stesso, senza mostrarlo."""
    n = normalizza_cartella(percorso)
    return hashlib.sha256(n.encode("utf-8")).hexdigest()[:12] if n else ""


def nome_progetto(percorso):
    """Ultimo elemento del percorso, oppure owner/repo per i repository."""
    p = (percorso or "").strip()
    if p.lower().startswith("repo "):
        return p[5:].strip()
    parti = [x for x in p.replace("\\", "/").split("/") if x]
    return parti[-1] if parti else ""


def riferimenti_da_testo(testo):
    """Id di sessione, UUID e pull request citati in un testo. Restituisce solo gli identificativi."""
    if not testo:
        return []
    trovati = []
    for m in RE_SESSIONE.finditer(testo):
        trovati.append(m.group(0))
    for m in RE_UUID.finditer(testo):
        trovati.append(m.group(0).lower())
    for m in RE_PR.finditer(testo):
        trovati.append(f"pr:{m.group(1)}/{m.group(2)}#{m.group(3)}".lower())
    for m in RE_PR_BREVE.finditer(testo):
        trovati.append(f"pr:{m.group(1)}/{m.group(2)}#{m.group(3)}".lower())
    visti, out = set(), []
    for t in trovati:
        if t not in visti:
            visti.add(t)
            out.append(t)
    return out[:MAX_RIFERIMENTI]


def arricchisci(s):
    """Aggiunge cartella_chiave e progetto se manca e c'è la cartella; normalizza riferimenti."""
    if s.get("cartella") and not s.get("cartella_chiave"):
        s["cartella_chiave"] = chiave_cartella(s["cartella"])
    if s.get("cartella") and not s.get("progetto"):
        s["progetto"] = nome_progetto(s["cartella"])
    rif = s.get("riferimenti")
    s["riferimenti"] = [str(r) for r in rif][:MAX_RIFERIMENTI] if isinstance(rif, list) else []
    return s


# --- somiglianza ----------------------------------------------------------------------------

PAROLE_VUOTE = set("""
il lo la i gli le un uno una di a da in con su per tra fra e ed o od ma che non del dello della dei degli delle
al allo alla ai agli alle dal dallo dalla dai dagli dalle nel nello nella nei negli nelle sul sullo sulla sui sugli
sulle come se più anche questo questa quello quella sono è era nuovo nuova
the a an of to in on for and or with from by at is are be this that new into via
""".split())
RE_PAROLA = re.compile(r"[a-zà-ÿ0-9]+", re.I)


def token(titolo):
    return {w for w in (x.lower() for x in RE_PAROLA.findall(titolo or "")) if len(w) > 2 and w not in PAROLE_VUOTE}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _ts(iso):
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return 0.0


# --- calcolo --------------------------------------------------------------------------------

SOGLIA_TITOLI = 0.5          # somiglianza dei titoli da sola
SOGLIA_TITOLI_VICINE = 0.25  # se nello stesso progetto e a meno di VICINE_ORE
VICINE_ORE = 2
TIPI_NON_ORIENTATI = {"stessa_cartella", "stessa_pr", "simile", "correlato", "duplicato"}


def id_arco(tipo, da, a):
    if tipo in TIPI_NON_ORIENTATI and a < da:
        da, a = a, da
    return f"{tipo}:{da}>{a}"


def _arco(tipo, da, a, confidenza, prova, fonte="auto"):
    return {"id": id_arco(tipo, da, a), "da": da, "a": a, "tipo": tipo, "confidenza": confidenza,
            "prova": prova, "fonte": fonte}


def _per_tempo(sessioni):
    return sorted(sessioni, key=lambda s: (s.get("ultima_attivita") or "", s.get("id") or ""))


def archi_automatici(sessioni, soglia=SOGLIA_TITOLI, soglia_vicine=SOGLIA_TITOLI_VICINE):
    per_id = {s["id"]: s for s in sessioni if s.get("id")}
    archi = {}

    def metti(arco):
        vecchio = archi.get(arco["id"])
        ordine = {"certo": 3, "probabile": 2, "proposta": 1}
        if not vecchio or ordine[arco["confidenza"]] > ordine[vecchio["confidenza"]]:
            archi[arco["id"]] = arco

    def orienta(x, y):
        return (x, y) if (x.get("ultima_attivita") or "") <= (y.get("ultima_attivita") or "") else (y, x)

    # 1. padre-figlio esplicito
    for s in sessioni:
        g = s.get("genitore")
        if g and g in per_id and g != s["id"]:
            metti(_arco("padre", g, s["id"], "certo", "campo genitore della sessione"))

    # 2. citazioni esplicite: id di sessione noti, e stessa pull request
    per_pr = {}
    for s in sessioni:
        for r in s.get("riferimenti", []):
            if r in per_id and r != s["id"]:
                x, y = orienta(per_id[r], s)
                metti(_arco("cita", x["id"], y["id"], "probabile", f"{s['id']} cita {r}"))
            elif r.startswith("pr:"):
                per_pr.setdefault(r, []).append(s)
    for pr, gruppo in per_pr.items():
        gruppo = _per_tempo({id(s): s for s in gruppo}.values())
        for x, y in zip(gruppo, gruppo[1:]):
            metti(_arco("stessa_pr", x["id"], y["id"], "probabile", f"entrambe citano {pr[3:]}"))

    # 3. stessa cartella o repository: archi solo tra sessioni consecutive
    per_cartella = {}
    for s in sessioni:
        if s.get("cartella_chiave"):
            per_cartella.setdefault(s["cartella_chiave"], []).append(s)
    for chiave, gruppo in per_cartella.items():
        gruppo = _per_tempo(gruppo)
        for x, y in zip(gruppo, gruppo[1:]):
            metti(_arco("stessa_cartella", x["id"], y["id"], "probabile",
                        f"stessa cartella ({x.get('progetto') or chiave})"))

    # 4. somiglianza dei titoli (e vicinanza nel tempo nello stesso progetto): solo proposte
    tok = {s["id"]: token(s.get("titolo")) for s in sessioni if s.get("id")}
    lista = [s for s in sessioni if s.get("id") and not s.get("interna")]
    for i, x in enumerate(lista):
        for y in lista[i + 1:]:
            j = jaccard(tok[x["id"]], tok[y["id"]])
            if j == 0:
                continue
            vicine = (x.get("progetto") and x.get("progetto") == y.get("progetto")
                      and abs(_ts(x.get("ultima_attivita")) - _ts(y.get("ultima_attivita"))) < VICINE_ORE * 3600)
            if j >= soglia or (vicine and j >= soglia_vicine):
                a, b = orienta(x, y)
                prova = f"titoli simili ({j:.0%})" + (", stesso progetto a meno di 2 h" if vicine else "")
                metti(_arco("simile", a["id"], b["id"], "proposta", prova))
    return list(archi.values())


ORIGINI_GRUPPO = {
    # campo della sessione: (prefisso dell'id, simbolo, descrizione, minimo di sessioni)
    "sezione_codex": ("sez", "🗂", "nella sezione di Codex", 1),
    "progetto_codex": ("prg", "🧭", "nel progetto di Codex", 1),
}


def _chiave_nome(prefisso, nome):
    return hashlib.sha256(f"{prefisso}:{nome.strip().lower()}".encode("utf-8")).hexdigest()[:12]


def gruppi_automatici(sessioni):
    """Gruppi proposti: cartelle con almeno due sessioni, sezioni e progetti già scelti dall'utente in Codex."""
    out = []
    per_cartella = {}
    for s in sessioni:
        if s.get("cartella_chiave") and not s.get("interna"):
            per_cartella.setdefault(s["cartella_chiave"], []).append(s)
    for chiave, gruppo in sorted(per_cartella.items()):
        if len(gruppo) < 2:
            continue
        nome = next((s.get("progetto") for s in gruppo if s.get("progetto")), chiave)
        macchine = sorted({s.get("macchina") or "remoto" for s in gruppo})
        out.append({"id": f"auto:{chiave}", "nome": f"📁 {nome}", "nome_proposto": nome, "origine": "cartella",
                    "membri": sorted(s["id"] for s in gruppo),
                    "prova": f"{len(gruppo)} sessioni nella stessa cartella ({', '.join(macchine)})"})
    for campo, (prefisso, simbolo, descrizione, minimo) in ORIGINI_GRUPPO.items():
        per_nome = {}
        for s in sessioni:
            nome = (s.get(campo) or "").strip()
            if nome and not s.get("interna"):
                per_nome.setdefault(nome, []).append(s)
        for nome, gruppo in sorted(per_nome.items()):
            if len(gruppo) < minimo:
                continue
            macchine = sorted({s.get("macchina") or "remoto" for s in gruppo})
            out.append({"id": f"auto:{prefisso}:{_chiave_nome(prefisso, nome)}", "nome": f"{simbolo} {nome}",
                        "nome_proposto": nome, "origine": campo, "membri": sorted(s["id"] for s in gruppo),
                        "prova": f"{len(gruppo)} thread {descrizione} “{nome}” ({', '.join(macchine)})"})
    return out


def applica_decisioni(archi, manuali, decisioni):
    """Unisce archi automatici e manuali; toglie i rifiutati, marca i confermati."""
    out = []
    for a in archi:
        d = decisioni.get(a["id"])
        if d == "rifiuta":
            continue
        if d == "conferma":
            a = dict(a, confidenza="confermato")
        out.append(a)
    for m in manuali:
        out.append(dict(m, confidenza="manuale", fonte="manuale"))
    return out
