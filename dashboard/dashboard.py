"""Dashboard locale delle sessioni Claude e Codex: elenco, collegamenti, gruppi, viste grafiche.

Avvio:  python dashboard.py        poi apri http://127.0.0.1:8765
Esporta per le altre macchine:  python dashboard.py --esporta [--ogni 60]
Prova con dati finti:  python dashboard.py --demo   (legge solo esempi/, non tocca ~/.codex né ~/.claude)
Legge solo file locali; non legge credenziali (auth.json, token).
Scrive solo: con --esporta (<CONDIVISA>/<MACCHINA>.json) e quando organizzi le sessioni dalla pagina
(<CONDIVISA>/organizza-<MACCHINA>.json; in --demo in demo-scritture/).
Fonti:
  - Codex: ~/.codex/state_5.sqlite (tabella threads) + coda dei file rollout
  - Claude locale: ~/.claude/projects/*/*.jsonl (+ eventuali subagents/)
  - Claude remoto (cloud / Remote Control): istantanea claude_remoto.json scritta da una sessione Claude
  - Altre macchine: <cartella condivisa>/<MACCHINA>.json, scritti con --esporta (vedi CONDIVISA)
"""
import argparse
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import collegamenti as col
import organizza as org

HOME = Path.home()
QUI = Path(__file__).resolve().parent
PORTA = int(os.environ.get("PORT", 8765))
ATTIVA_SE_MINUTI = 3  # attività più recente di così = "attiva"
MACCHINA = os.environ.get("COMPUTERNAME", "questa macchina").upper()
# cartella condivisa tra le macchine: per impostazione "dati" accanto allo script, così basta tenere
# la cartella della dashboard in una cartella sincronizzata visibile da tutte le macchine
CONDIVISA = Path(os.environ.get("DASHBOARD_CONDIVISA") or QUI / "dati")
VECCHIA_SE_MINUTI = 5  # un'esportazione più vecchia di così viene segnalata
# nell'esportazione restano solo questi campi: niente messaggi né percorsi completi nella cartella condivisa.
# cartella_chiave è un'impronta del percorso (serve a riconoscere la stessa cartella su macchine diverse),
# progetto è il nome dell'ultima cartella; riferimenti contiene solo id di sessione e pull request citati.
CAMPI_ESPORTATI = ("strumento", "tipo", "titolo", "modello", "stato", "ultima_attivita", "id",
                   "inizio", "genitore", "riferimenti", "cartella_chiave", "progetto", "sezione_codex", "progetto_codex")
# modalità dimostrativa (--demo): tutte le fonti vengono da esempi/, con orari spostati su adesso
ESEMPI = QUI / "esempi"
DEMO = False
DEMO_RIFERIMENTO = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)  # "adesso" negli orari degli esempi
DEMO_SCRITTURE = QUI / "demo-scritture"
STATICI = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
           "/app.js": ("app.js", "text/javascript"), "/stile.css": ("stile.css", "text/css")}
MAX_CORPO = 64_000
MAX_THREAD = 80     # thread Codex letti (escluse le revisioni guardian)
MAX_GUARDIAN = 20   # revisioni guardian lette
# avvisi
BLOCCATA_ORE = 2
ORFANA_GIORNI = 7
CONTESTO_PIENO = 0.8
RE_CONTESTO = re.compile(r"contesto\s+(\d+(?:[.,]\d+)?)\s*([kM])\s*/\s*(\d+(?:[.,]\d+)?)\s*([kM])", re.I)


def attiva_demo():
    global DEMO, CONDIVISA, MACCHINA
    DEMO, CONDIVISA, MACCHINA = True, ESEMPI, "DEMO"


def ora_iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


def ts_da_iso(iso):
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return 0.0


def stato_da_eta(ts):
    if not ts:
        return "sconosciuto"
    return "attiva" if time.time() - ts < ATTIVA_SE_MINUTI * 60 else "ferma"


def sposta_demo(dati):
    """In --demo gli orari degli esempi sono scritti rispetto a DEMO_RIFERIMENTO: li sposta su adesso."""
    delta = datetime.now(timezone.utc) - DEMO_RIFERIMENTO

    def sposta(v):
        try:
            return (datetime.fromisoformat(v) + delta).isoformat()
        except (TypeError, ValueError):
            return v
    if "generata" in dati:
        dati["generata"] = sposta(dati["generata"])
    for s in dati.get("sessioni", []):
        s["ultima_attivita"] = sposta(s.get("ultima_attivita"))
        if s.get("inizio"):
            s["inizio"] = sposta(s["inizio"])
    return dati


def leggi_json(p):
    dati = json.loads(p.read_text(encoding="utf-8"))
    return sposta_demo(dati) if DEMO else dati


def eta_minuti(p, dati):
    """Età di un file in minuti: dall'orario del file; in --demo dal campo "generata" (il file è appena scaricato)."""
    if DEMO:
        try:
            return (datetime.now(timezone.utc) - datetime.fromisoformat(dati["generata"])).total_seconds() / 60
        except (KeyError, TypeError, ValueError):
            pass
    return (time.time() - p.stat().st_mtime) / 60


def coda_testo(percorso, byte=64_000):
    """Ultimi byte di un file come testo, senza leggerlo tutto (alcuni rollout superano i 5 MB).
    Se la lettura parte a metà file, la prima riga (tagliata) viene scartata."""
    try:
        with open(percorso, "rb") as f:
            f.seek(0, os.SEEK_END)
            inizio = max(0, f.tell() - byte)
            f.seek(inizio)
            testo = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return testo.split("\n", 1)[1] if inizio and "\n" in testo else testo


def coda_file(percorso, byte=64_000):
    """Ultime righe JSON di un file."""
    out = []
    for r in coda_testo(percorso, byte).splitlines():
        try:
            out.append(json.loads(r))
        except ValueError:
            pass
    return out


def candidati_riferimenti(testo, proprio_id):
    """Riferimenti espliciti (session_..., pull request) e insieme degli UUID citati, da risolvere dopo."""
    rif = [r for r in col.riferimenti_da_testo(re.sub(col.RE_UUID, " ", testo)) if r != proprio_id]
    uuid = {u.lower() for u in col.RE_UUID.findall(testo)} - {str(proprio_id).lower()}
    return rif, uuid


def codex():
    db = HOME / ".codex" / "state_5.sqlite"
    if not db.exists():
        return [], "state_5.sqlite non trovato"
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        c.row_factory = sqlite3.Row
        colonne = {r["name"] for r in c.execute("pragma table_info(threads)")}
        tabelle = {r["name"] for r in c.execute("select name from sqlite_master where type='table'")}
        # colonne facoltative, usate solo se esistono. Verificato con sonda.py (2026-11-05): in threads c'è
        # attached_thread_parent_id; i legami madre-figlia stanno anche nella tabella thread_spawn_edges.
        genitore = next((x for x in ("attached_thread_parent_id", "parent_thread_id", "parent_id") if x in colonne), None)
        inizio = next((x for x in ("created_at_ms", "created_at") if x in colonne), None)
        extra = (f", {genitore} as genitore" if genitore else "") + (f", {inizio} as inizio" if inizio else "")
        # organizzazione già fatta in Codex: sezioni e progetti (verificati con sonda.py il 2026-11-05)
        for colonna, tabella, alias in (("thread_section_id", "thread_sections", "sezione"), ("project_id", "projects", "progetto")):
            extra += f", {colonna} as {alias}" if colonna in colonne and tabella in tabelle else f", null as {alias}"
        base = ("select id, rollout_path, cwd, coalesce(name, title, '') as titolo, model, originator,"
                f" thread_source, archived, updated_at_ms, tokens_used{extra} from threads")
        guardia = "(coalesce(thread_source, '') = 'guardian_review' or coalesce(name, title, '') = 'Guardian review')"
        # le revisioni guardian sono la maggior parte dei thread: hanno un limite a parte, così non escludono quelli veri
        righe = c.execute(f"{base} where not {guardia} order by updated_at_ms desc limit {MAX_THREAD}").fetchall()
        righe += c.execute(f"{base} where {guardia} order by updated_at_ms desc limit {MAX_GUARDIAN}").fetchall()
        nomi = {}
        for tabella in ("thread_sections", "projects"):
            if tabella in tabelle:
                nomi[tabella] = {r["id"]: r["name"] for r in c.execute(f"select id, name from {tabella}")}
        figli = {}
        if "thread_spawn_edges" in tabelle:
            figli = {r["child_thread_id"]: r["parent_thread_id"]
                     for r in c.execute("select parent_thread_id, child_thread_id from thread_spawn_edges")}
        rc = c.execute(
            "select server_name, remote_control_enabled, updated_at from remote_control_enrollments"
        ).fetchall()
        c.close()
    except sqlite3.Error as e:
        return [], f"errore sqlite: {e}"
    remoto = any(r["remote_control_enabled"] for r in rc)
    sessioni = []
    for r in righe:
        ts = (r["updated_at_ms"] or 0) / 1000
        stato, ultimo, rif, uuid = stato_da_eta(ts), "", [], set()
        if r["rollout_path"] and time.time() - ts < 7 * 86400:
            testo = coda_testo(r["rollout_path"])
            rif, uuid = candidati_riferimenti(testo, r["id"])
            eventi = []
            for riga in testo.splitlines():
                try:
                    e = json.loads(riga)
                except ValueError:
                    continue
                if e.get("type") == "event_msg":
                    eventi.append(e.get("payload", {}))
            fasi = [p for p in eventi if p.get("type") in ("task_started", "task_complete")]
            if fasi and fasi[-1].get("type") == "task_started":
                stato = "in lavoro" if stato == "attiva" else "interrotta?"
            fine = [p for p in eventi if p.get("type") == "task_complete"]
            if fine:
                ultimo = (fine[-1].get("last_agent_message") or "")[:240]
        # le revisioni guardian più vecchie non hanno thread_source: si riconoscono dal titolo
        guardian = r["thread_source"] == "guardian_review" or r["titolo"] == "Guardian review"
        ini = r["inizio"] if inizio else None
        if isinstance(ini, (int, float)) and ini > 1e11:
            ini = ini / 1000
        sessioni.append({
            "strumento": "Codex",
            "tipo": "revisione guardian" if guardian else (r["originator"] or ""),
            "titolo": r["titolo"][:120],
            "cartella": r["cwd"] or "",
            "modello": r["model"] or "",
            "stato": "archiviata" if r["archived"] else stato,
            "ultima_attivita": ora_iso(ts),
            "inizio": ora_iso(ini) if isinstance(ini, (int, float)) else None,
            "ultimo_messaggio": ultimo,
            "id": r["id"],
            "genitore": figli.get(r["id"]) or (r["genitore"] if genitore else None) or None,
            "sezione_codex": nomi.get("thread_sections", {}).get(r["sezione"]) or None,
            "progetto_codex": nomi.get("projects", {}).get(r["progetto"]) or None,
            "riferimenti": rif,
            "_uuid": uuid,
            "interna": guardian,
        })
    nota = f"remote control Codex: {'attivo' if remoto else 'non attivo'} ({len(rc)} registrazione/i)"
    return sessioni, nota


def primo_messaggio_utente(percorso, righe_max=200):
    """Testo del primo messaggio dell'utente, come titolo di ripiego."""
    try:
        with open(percorso, encoding="utf-8", errors="replace") as f:
            for i, r in enumerate(f):
                if i > righe_max:
                    break
                try:
                    o = json.loads(r)
                except ValueError:
                    continue
                if o.get("type") == "custom-title" and o.get("customTitle"):
                    return o["customTitle"]
                if o.get("type") != "user":
                    continue
                c = o.get("message", {}).get("content")
                if isinstance(c, list):
                    c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
                if isinstance(c, str) and c.strip() and not c.lstrip().startswith("<"):
                    return " ".join(c.split())
    except OSError:
        pass
    return ""


def primo_orario(percorso, righe_max=30):
    """Campo "timestamp" della prima riga che lo contiene (inizio della sessione)."""
    try:
        with open(percorso, encoding="utf-8", errors="replace") as f:
            for i, r in enumerate(f):
                if i > righe_max:
                    break
                try:
                    t = json.loads(r).get("timestamp")
                except (ValueError, AttributeError):
                    continue
                if isinstance(t, str) and ts_da_iso(t.replace("Z", "+00:00")):
                    return datetime.fromisoformat(t.replace("Z", "+00:00")).isoformat()
    except OSError:
        pass
    return None


def claude_locale():
    radice = HOME / ".claude" / "projects"
    sessioni = []
    # sessioni principali in */*.jsonl; i subagenti (se presenti) in */<sessione>/subagents/*.jsonl
    file = [(f, None) for f in radice.glob("*/*.jsonl")]
    file += [(f, f.parent.parent.name) for f in radice.glob("*/*/subagents/*.jsonl")]
    for f, genitore in file:
        ts = f.stat().st_mtime
        titolo = nome = titolo_ai = ultimo_prompt = cwd = ""
        remoto = False
        testo = coda_testo(f, 256_000)
        for riga in testo.splitlines():
            try:
                o = json.loads(riga)
            except ValueError:
                continue
            t = o.get("type")
            if t == "custom-title":
                titolo = o.get("customTitle") or titolo
            elif t == "agent-name":
                nome = o.get("agentName") or nome
            elif t == "ai-title":  # titolo generato: nome del campo da confermare con sonda.py
                titolo_ai = next((v for k, v in o.items() if k in ("aiTitle", "title", "customTitle") and isinstance(v, str)),
                                 titolo_ai)
            elif t == "last-prompt":
                ultimo_prompt = o.get("lastPrompt") or ultimo_prompt
            elif t == "bridge-session":
                remoto = True
            if o.get("cwd"):
                cwd = o["cwd"]
        if not (titolo or nome or titolo_ai):
            titolo = primo_messaggio_utente(f)
        rif, uuid = candidati_riferimenti(testo, f.stem)
        sessioni.append({
            "strumento": "Claude Code",
            "tipo": "subagente" if genitore else ("locale + remote control" if remoto else "locale"),
            "titolo": (titolo or nome or titolo_ai or f.stem)[:120],
            "cartella": cwd or f.parent.name,
            "modello": "",
            "stato": stato_da_eta(ts),
            "ultima_attivita": ora_iso(ts),
            "inizio": primo_orario(f),
            "ultimo_messaggio": (ultimo_prompt or "")[:240],
            "id": f.stem,
            "genitore": genitore,
            "riferimenti": rif,
            "_uuid": uuid,
            "interna": False,
        })
    return sessioni, f"{len(sessioni)} trascrizioni in {radice}"


def claude_remoto():
    # si usa la più recente tra la copia accanto allo script e quella nella cartella condivisa
    if DEMO:
        candidati = [ESEMPI / "claude_remoto.json"]
    else:
        candidati = [QUI / "claude_remoto.json"] + ([CONDIVISA / "claude_remoto.json"] if CONDIVISA else [])
    esistenti = [p for p in candidati if p.exists()]
    if not esistenti:
        return [], "istantanea assente: chiedi a Claude di rigenerare claude_remoto.json"
    p = max(esistenti, key=lambda x: x.stat().st_mtime)
    try:
        dati = leggi_json(p)
    except ValueError as e:
        return [], f"istantanea illeggibile: {e}"
    eta = eta_minuti(p, dati)
    return dati.get("sessioni", []), f"istantanea di {eta:.0f} minuti fa ({dati.get('generata', '?')})"


MANUALI = [
    {"strumento": "Cowork", "nota": "non raggiungibile: il filtro per le sessioni Cowork non è disponibile (verificato 2026-10-20)"},
    {"strumento": "ChatGPT", "nota": "nessuna API nota per elencare le chat: controllo manuale"},
]


def altre_macchine(avvisi=None):
    """Sessioni esportate da altre macchine nella cartella condivisa."""
    if not CONDIVISA or not CONDIVISA.exists():
        return [], f"cartella condivisa {CONDIVISA} assente: nessuna esportazione"
    sessioni, note = [], []
    for p in sorted(CONDIVISA.glob("*.json")):
        if p.name == "claude_remoto.json" or p.name.startswith(org.PREFISSO) or p.stem.upper() == MACCHINA:
            continue
        try:
            dati = leggi_json(p)
        except (OSError, ValueError) as e:
            note.append(f"{p.stem}: illeggibile ({e})")
            continue
        chi = str(dati.get("macchina") or "").upper()
        if chi == MACCHINA:
            continue  # copia di conflitto di OneDrive del proprio file (es. MANAS-Dedalo.json)
        if chi != p.stem.upper():
            note.append(f"{p.name}: ignorato, contiene dati di {chi or '?'} (copia di conflitto della sincronizzazione?)")
            continue
        eta = eta_minuti(p, dati)
        vecchia = eta > VECCHIA_SE_MINUTI
        for s in dati.get("sessioni", []):
            s = dict(s, macchina=chi, interna=False, ultimo_messaggio="", cartella="")
            if vecchia and s.get("stato") in ("attiva", "in lavoro"):
                s["stato"] = "sconosciuto"  # esportazione ferma: lo stato non è più affidabile
            sessioni.append(s)
        note.append(f"{p.stem}: aggiornata {eta:.0f} min fa" + (" ⚠ esportazione ferma?" if vecchia else ""))
        if vecchia and avvisi is not None:
            avvisi.append({"livello": "attenzione", "tipo": "esportazione_ferma", "sessione": None,
                           "testo": f"L'esportazione di {chi} è ferma da {eta:.0f} minuti: stati non affidabili"})
    return sessioni, "; ".join(note) or "nessuna altra macchina"


def demo_locale():
    """Sessioni finte della "macchina locale" in --demo (al posto di Codex e Claude locale)."""
    p = ESEMPI / "locale" / "sessioni.json"
    return leggi_json(p).get("sessioni", []), f"dati finti da {p.relative_to(QUI).as_posix()}"


def prepara(sessioni):
    """Campi derivati e risoluzione degli UUID citati verso le sessioni note."""
    noti = {str(s.get("id")).lower(): s.get("id") for s in sessioni if s.get("id")}
    for s in sessioni:
        uuid = s.pop("_uuid", set()) or set()
        col.arricchisci(s)
        extra = [noti[u] for u in sorted(uuid) if u in noti and noti[u] != s.get("id")]
        s["riferimenti"] = list(dict.fromkeys(s["riferimenti"] + extra))[:col.MAX_RIFERIMENTI]
        s.setdefault("genitore", None)
        s.setdefault("inizio", None)
        s.setdefault("sezione_codex", None)
        s.setdefault("progetto_codex", None)
    return sessioni


def raccogli_locali():
    """Fonti di questa macchina, ognuna isolata: una fonte rotta non ferma le altre."""
    fonti, tutte = {}, []
    locali = (("Esempi locali", demo_locale),) if DEMO else (("Codex", codex), ("Claude locale", claude_locale))
    for nome, fn in locali:
        try:
            s, nota = fn()
        except Exception as e:
            s, nota = [], f"errore: {e}"
        for x in s:
            x["macchina"] = MACCHINA
        fonti[f"{nome} ({MACCHINA})"] = {"n": len(s), "nota": nota}
        tutte.extend(s)
    return fonti, tutte


def esporta():
    """Scrive <CONDIVISA>/<MACCHINA>.json con i soli CAMPI_ESPORTATI (ultimi 30 giorni, senza revisioni guardian)."""
    if not CONDIVISA:
        raise SystemExit("cartella condivisa non impostata")
    CONDIVISA.mkdir(parents=True, exist_ok=True)
    _, tutte = raccogli_locali()
    prepara(tutte)
    limite = datetime.fromtimestamp(time.time() - 30 * 86400, timezone.utc).isoformat()
    scelte = [{k: s.get(k) for k in CAMPI_ESPORTATI} for s in tutte
              if not s.get("interna") and (s.get("ultima_attivita") or "") >= limite]
    dest = CONDIVISA / f"{MACCHINA}.json"
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps({"macchina": MACCHINA, "generata": ora_iso(time.time()), "sessioni": scelte},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, dest)  # sostituzione in un colpo: chi legge non vede mai un file a metà
    return dest, len(scelte)


def unisci_doppie(sessioni):
    """Stesso id su più macchine (sessione ripresa altrove): resta la più recente, con l'elenco delle altre."""
    per_id = {}
    for s in sessioni:
        per_id.setdefault(s.get("id"), []).append(s)
    out = []
    for lista in per_id.values():
        lista.sort(key=lambda s: s.get("ultima_attivita") or "", reverse=True)
        s = lista[0]
        if len(lista) > 1:
            s["anche_su"] = sorted({x.get("macchina") or "remoto" for x in lista[1:]} - {s.get("macchina") or "remoto"})
            attive = {x.get("macchina") or "remoto" for x in lista if x.get("stato") in ("attiva", "in lavoro")}
            s["attiva_su"] = sorted(attive) if len(attive) > 1 else []
            s["riferimenti"] = list(dict.fromkeys(r for x in lista for r in x.get("riferimenti", [])))
        out.append(s)
    return out


def raccogli(avvisi=None):
    fonti, tutte = raccogli_locali()
    for nome, fn in (("Claude remoto", claude_remoto), ("Altre macchine", lambda: altre_macchine(avvisi))):
        try:
            s, nota = fn()
        except Exception as e:
            s, nota = [], f"errore: {e}"
        fonti[nome] = {"n": len(s), "nota": nota}
        tutte.extend(s)
    # una sessione locale collegata in remote control compare anche nell'istantanea remota: si tiene quella remota
    remoti = {s.get("titolo") for s in tutte if s.get("strumento") == "Claude (remoto)"}
    tutte = [s for s in tutte if not (s.get("strumento") == "Claude Code" and s.get("titolo") in remoti
                                      and s.get("tipo") != "subagente")]
    prepara(tutte)
    tutte = unisci_doppie(tutte)
    tutte.sort(key=lambda s: s.get("ultima_attivita") or "", reverse=True)
    return {"generato": ora_iso(time.time()), "fonti": fonti, "manuali": MANUALI, "sessioni": tutte}


# --- organizzazione e grafo -------------------------------------------------------------------

def cartella_scritture():
    return DEMO_SCRITTURE if DEMO else CONDIVISA


def cartelle_registri():
    return [ESEMPI, DEMO_SCRITTURE] if DEMO else [CONDIVISA]


def calcola_avvisi(sessioni, archi_in_attesa, avvisi):
    adesso = time.time()
    for s in sessioni:
        eta_h = (adesso - ts_da_iso(s.get("ultima_attivita"))) / 3600 if s.get("ultima_attivita") else None
        if s.get("stato") == "bloccata":
            lungo = eta_h is not None and eta_h > BLOCCATA_ORE
            avvisi.append({"livello": "attenzione" if lungo else "info", "tipo": "bloccata", "sessione": s["id"],
                           "testo": f"Attende una risposta da {eta_h:.0f} h" if lungo else "Attende una risposta"})
        if s.get("stato") == "fallita":
            avvisi.append({"livello": "attenzione", "tipo": "fallita", "sessione": s["id"],
                           "testo": "L'ultimo turno è terminato con errore"})
        m = RE_CONTESTO.search(s.get("ultimo_messaggio") or "")
        if m:
            def num(v, u):
                return float(v.replace(",", ".")) * (1000 if u.lower() == "k" else 1_000_000)
            usato, totale = num(m.group(1), m.group(2)), num(m.group(3), m.group(4))
            if totale and usato / totale >= CONTESTO_PIENO:
                avvisi.append({"livello": "attenzione", "tipo": "contesto", "sessione": s["id"],
                               "testo": f"Contesto quasi pieno ({usato / totale:.0%})"})
        if (not s.get("gruppo") and not s.get("interna") and eta_h is not None and eta_h > ORFANA_GIORNI * 24
                and s.get("stato") not in ("archiviata",)):
            avvisi.append({"livello": "info", "tipo": "orfana", "sessione": s["id"],
                           "testo": f"In nessun gruppo da più di {ORFANA_GIORNI} giorni"})
        if s.get("attiva_su"):
            avvisi.append({"livello": "attenzione", "tipo": "doppia", "sessione": s["id"],
                           "testo": f"Stessa sessione attiva su più macchine: {', '.join(s['attiva_su'])}"})
    if archi_in_attesa:
        avvisi.append({"livello": "info", "tipo": "proposte", "sessione": None,
                       "testo": f"{archi_in_attesa} collegamenti o gruppi proposti da confermare"})
    ordine = {"attenzione": 0, "info": 1}
    avvisi.sort(key=lambda a: (ordine.get(a["livello"], 2), a["tipo"]))
    return avvisi


def da_confermare(arco):
    """Proposte da mostrare nella casella: non gli archi "stessa cartella", già riassunti dai gruppi automatici."""
    return arco["confidenza"] in ("probabile", "proposta") and arco["tipo"] != "stessa_cartella"


def costruisci_grafo():
    avvisi = []
    dati = raccogli(avvisi)
    sessioni = dati["sessioni"]
    operazioni, note_org = org.leggi_registri(cartelle_registri())
    stato = org.fondi(operazioni)
    gruppi = stato["gruppi"]
    for s in sessioni:
        gid, fonte = stato["membri"].get(s["id"]), "manuale"
        if not gid or gid not in gruppi:
            gid, fonte = org.gruppo_da_regole(s, stato["regole"]), "regola"
        s["gruppo"] = gid if gid in gruppi else None
        s["gruppo_fonte"] = fonte if s["gruppo"] else None
        s["gruppo_percorso"] = org.percorso_gruppo(gruppi, s["gruppo"]) if s["gruppo"] else ""
        attributi = stato["sessioni"].get(s["id"], {})
        for campo in org.CAMPI_SESSIONE:
            s[campo] = attributi.get(campo, [] if campo == "etichette" else (False if campo == "nascosta" else ""))
    archi = col.applica_decisioni(col.archi_automatici(sessioni), list(stato["collegamenti"].values()),
                                  stato["decisioni"])
    auto = [dict(g, decisione=stato["decisioni"].get(g["id"])) for g in col.gruppi_automatici(sessioni)]
    in_attesa = sum(1 for a in archi if da_confermare(a)) + \
        sum(1 for g in auto if not g["decisione"])
    lista_gruppi = []
    for g in sorted(gruppi.values(), key=lambda g: org.percorso_gruppo(gruppi, g["id"]).lower()):
        membri = {s["id"] for s in sessioni if s["gruppo"] in org.discendenti(gruppi, g["id"])}
        lista_gruppi.append(dict(g, percorso=org.percorso_gruppo(gruppi, g["id"]), n=len(membri)))
    dati.update({
        "macchina": MACCHINA, "demo": DEMO,
        "gruppi": lista_gruppi, "gruppi_auto": auto, "archi": archi,
        "colonne": stato["colonne"], "regole": list(stato["regole"].values()), "decisioni": stato["decisioni"],
        "avvisi": calcola_avvisi(sessioni, in_attesa, avvisi),
        "organizza": {"note": note_org, "scrive_in": str(cartella_scritture() / f"{org.PREFISSO}{MACCHINA}.json")},
    })
    dati["fonti"]["Organizzazione"] = {"n": len(operazioni), "nota": "; ".join(note_org) or "nessuna operazione"}
    return dati


def markdown_gruppo(dati, gid):
    """Riassunto Markdown di un gruppo (con sottogruppi), da incollare in una nuova chat."""
    gruppi = {g["id"]: g for g in dati["gruppi"]}
    if gid and gid not in gruppi:
        return None
    if gid:
        ids = org.discendenti(gruppi, gid)
        sessioni = [s for s in dati["sessioni"] if s.get("gruppo") in ids]
        titolo = gruppi[gid]["percorso"]
    else:
        sessioni = [s for s in dati["sessioni"] if not s.get("gruppo")]
        titolo = "Sessioni senza gruppo"
    scelte = {s["id"] for s in sessioni}
    titoli = {s["id"]: s.get("titolo") or s["id"] for s in dati["sessioni"]}
    righe = [f"# {titolo}", "", f"Generato {dati['generato'][:16].replace('T', ' ')} UTC · {len(sessioni)} sessioni", ""]
    for s in sessioni:
        righe.append(f"## {s.get('titolo') or s['id']}")
        righe.append(f"- Stato: {s.get('stato')} · {s.get('strumento')}" + (f" @{s['macchina']}" if s.get("macchina") else "")
                     + f" · ultima attività {str(s.get('ultima_attivita') or '')[:16].replace('T', ' ')}")
        righe.append(f"- Id: `{s['id']}`" + (f" · progetto {s['progetto']}" if s.get("progetto") else "")
                     + (f" · anche su {', '.join(s['anche_su'])}" if s.get("anche_su") else ""))
        if s.get("gruppo_percorso") and gid and s["gruppo"] != gid:
            righe.append(f"- Sottogruppo: {s['gruppo_percorso']}")
        for campo, nome in (("prossima_azione", "Prossima azione"), ("nota", "Nota")):
            if s.get(campo):
                righe.append(f"- {nome}: {s[campo]}")
        if s.get("etichette"):
            righe.append(f"- Etichette: {', '.join(s['etichette'])}")
        legami = [a for a in dati["archi"] if s["id"] in (a["da"], a["a"])
                  and a["confidenza"] != "proposta" and a["tipo"] != "stessa_cartella"]
        for a in legami:
            altro = a["a"] if a["da"] == s["id"] else a["da"]
            verso = "→" if a["da"] == s["id"] else "←"
            dentro = "" if altro in scelte else " (fuori dal gruppo)"
            righe.append(f"- {a['tipo']} {verso} {titoli.get(altro, altro)}{dentro}")
        righe.append("")
    return "\n".join(righe)


# --- server -----------------------------------------------------------------------------------

def scrittura_ammessa(intestazioni):
    """Solo richieste da questa dashboard: Host locale, Origin locale (se presente), corpo JSON."""
    locali = {f"127.0.0.1:{PORTA}", f"localhost:{PORTA}"}
    if intestazioni.get("Host") not in locali:
        return False, "host non ammesso"
    origine = intestazioni.get("Origin")
    if origine is not None and origine not in {f"http://{h}" for h in locali}:
        return False, "origine non ammessa"
    if (intestazioni.get("Content-Type") or "").split(";")[0].strip() != "application/json":
        return False, "serve Content-Type: application/json"
    return True, ""


class Gestore(BaseHTTPRequestHandler):
    def rispondi(self, codice, corpo, tipo="application/json"):
        if isinstance(corpo, (dict, list)):
            corpo = json.dumps(corpo, ensure_ascii=False)
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(codice)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/sessioni":
            self.rispondi(200, raccogli())
        elif url.path == "/api/grafo":
            self.rispondi(200, costruisci_grafo())
        elif url.path == "/api/esporta.md":
            gid = parse_qs(url.query).get("gruppo", [""])[0]
            testo = markdown_gruppo(costruisci_grafo(), gid)
            if testo is None:
                self.rispondi(404, {"errore": "gruppo inesistente"})
            else:
                self.rispondi(200, testo, "text/markdown")
        elif url.path in STATICI:
            nome, tipo = STATICI[url.path]
            self.rispondi(200, (QUI / nome).read_bytes(), tipo)
        else:
            self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path != "/api/organizza":
            self.send_error(404)
            return
        ok, motivo = scrittura_ammessa(self.headers)
        if not ok:
            self.rispondi(403, {"errore": motivo})
            return
        try:
            lunghezza = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            lunghezza = -1
        if not 0 < lunghezza <= MAX_CORPO:
            self.rispondi(413, {"errore": f"corpo assente o oltre {MAX_CORPO} byte"})
            return
        try:
            corpo = json.loads(self.rfile.read(lunghezza).decode("utf-8"))
            n = org.aggiungi_operazioni(cartella_scritture(), MACCHINA, corpo.get("operazioni"))
        except (ValueError, AttributeError) as e:
            self.rispondi(400, {"errore": str(e)})
            return
        except OSError as e:
            self.rispondi(500, {"errore": f"scrittura non riuscita: {e}"})
            return
        self.rispondi(200, {"ok": True, "operazioni": n})

    def log_message(self, *a):
        pass


def crea_server(porta=None):
    # su Windows il riuso dell'indirizzo lascerebbe partire due dashboard sulla stessa porta senza errore
    ThreadingHTTPServer.allow_reuse_address = False
    return ThreadingHTTPServer(("127.0.0.1", PORTA if porta is None else porta), Gestore)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Dashboard sessioni Claude e Codex")
    ap.add_argument("--esporta", action="store_true", help="scrive l elenco sessioni nella cartella condivisa")
    ap.add_argument("--ogni", type=int, default=0, help="con --esporta: ripete ogni N secondi (0 = una volta)")
    ap.add_argument("--demo", action="store_true", help="dati finti da esempi/: non legge ~/.codex né ~/.claude")
    a = ap.parse_args()
    if a.demo:
        if a.esporta:
            raise SystemExit("--demo non esporta: i dati finti non vanno nella cartella condivisa")
        attiva_demo()
        print(f"Modalità dimostrativa: solo dati finti da {ESEMPI}; le modifiche vanno in {DEMO_SCRITTURE}")
    if a.esporta:
        while True:
            try:
                dest, n = esporta()
                print(f"{datetime.now():%H:%M:%S} esportate {n} sessioni in {dest}")
            except OSError as e:  # la sincronizzazione può bloccare il file per un attimo durante la sincronizzazione
                print(f"{datetime.now():%H:%M:%S} esportazione non riuscita: {e}")
            if a.ogni <= 0:
                break
            time.sleep(a.ogni)
    else:
        try:
            server = crea_server()
        except OSError:
            raise SystemExit(f"Porta {PORTA} occupata: la dashboard è forse già avviata. Apri http://127.0.0.1:{PORTA}")
        print(f"Dashboard {MACCHINA} su http://127.0.0.1:{PORTA}  (Ctrl+C per fermare)")
        server.serve_forever()
