"""Dashboard locale delle sessioni Claude e Codex (sola lettura).

Avvio:  python dashboard.py        poi apri http://127.0.0.1:8765
Esporta per le altre macchine:  python dashboard.py --esporta [--ogni 60]
Legge solo file locali; non legge credenziali (auth.json, token). Scrive solo con --esporta.
Fonti:
  - Codex: ~/.codex/state_5.sqlite (tabella threads) + coda dei file rollout
  - Claude locale: ~/.claude/projects/*/*.jsonl
  - Claude remoto (cloud / Remote Control): istantanea claude_remoto.json scritta da una sessione Claude
  - Altre macchine: <cartella condivisa>/<MACCHINA>.json, scritti con --esporta (vedi CONDIVISA)
"""
import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOME = Path.home()
QUI = Path(__file__).resolve().parent
PORTA = int(os.environ.get("PORT", 8765))
ATTIVA_SE_MINUTI = 3  # attività più recente di così = "attiva"
MACCHINA = os.environ.get("COMPUTERNAME", "questa macchina").upper()
# cartella condivisa tra le macchine: per impostazione "dati" accanto allo script, così basta tenere
# la cartella della dashboard in una cartella sincronizzata visibile da tutte le macchine
CONDIVISA = Path(os.environ.get("DASHBOARD_CONDIVISA") or QUI / "dati")
VECCHIA_SE_MINUTI = 5  # un'esportazione più vecchia di così viene segnalata
# nell'esportazione restano solo questi campi: niente messaggi né cartelle nella cartella condivisa
CAMPI_ESPORTATI = ("strumento", "tipo", "titolo", "modello", "stato", "ultima_attivita", "id")


def ora_iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None


def stato_da_eta(ts):
    if not ts:
        return "sconosciuto"
    return "attiva" if time.time() - ts < ATTIVA_SE_MINUTI * 60 else "ferma"


def coda_file(percorso, byte=64_000):
    """Ultime righe JSON di un file, senza leggerlo tutto (alcuni rollout superano i 5 MB)."""
    try:
        with open(percorso, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - byte))
            righe = f.read().decode("utf-8", "replace").splitlines()[1:]
    except OSError:
        return []
    out = []
    for r in righe:
        try:
            out.append(json.loads(r))
        except ValueError:
            pass
    return out


def codex():
    db = HOME / ".codex" / "state_5.sqlite"
    if not db.exists():
        return [], "state_5.sqlite non trovato"
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        c.row_factory = sqlite3.Row
        righe = c.execute(
            "select id, rollout_path, cwd, coalesce(name, title, '') as titolo, model, originator,"
            " thread_source, archived, updated_at_ms, tokens_used from threads"
            " order by updated_at_ms desc limit 60"
        ).fetchall()
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
        stato, ultimo = stato_da_eta(ts), ""
        if r["rollout_path"] and time.time() - ts < 7 * 86400:
            eventi = [e.get("payload", {}) for e in coda_file(r["rollout_path"]) if e.get("type") == "event_msg"]
            fasi = [p for p in eventi if p.get("type") in ("task_started", "task_complete")]
            if fasi and fasi[-1].get("type") == "task_started":
                stato = "in lavoro" if stato == "attiva" else "interrotta?"
            fine = [p for p in eventi if p.get("type") == "task_complete"]
            if fine:
                ultimo = (fine[-1].get("last_agent_message") or "")[:240]
        # le revisioni guardian più vecchie non hanno thread_source: si riconoscono dal titolo
        guardian = r["thread_source"] == "guardian_review" or r["titolo"] == "Guardian review"
        sessioni.append({
            "strumento": "Codex",
            "tipo": "revisione guardian" if guardian else (r["originator"] or ""),
            "titolo": r["titolo"][:120],
            "cartella": r["cwd"] or "",
            "modello": r["model"] or "",
            "stato": "archiviata" if r["archived"] else stato,
            "ultima_attivita": ora_iso(ts),
            "ultimo_messaggio": ultimo,
            "id": r["id"],
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


def claude_locale():
    radice = HOME / ".claude" / "projects"
    sessioni = []
    for f in radice.glob("*/*.jsonl"):
        ts = f.stat().st_mtime
        titolo = nome = ultimo_prompt = cwd = ""
        remoto = False
        for o in coda_file(f, 256_000):
            t = o.get("type")
            if t == "custom-title":
                titolo = o.get("customTitle") or titolo
            elif t == "agent-name":
                nome = o.get("agentName") or nome
            elif t == "last-prompt":
                ultimo_prompt = o.get("lastPrompt") or ultimo_prompt
            elif t == "bridge-session":
                remoto = True
            if o.get("cwd"):
                cwd = o["cwd"]
        if not (titolo or nome):
            titolo = primo_messaggio_utente(f)
        sessioni.append({
            "strumento": "Claude Code",
            "tipo": "locale + remote control" if remoto else "locale",
            "titolo": (titolo or nome or f.stem)[:120],
            "cartella": cwd or f.parent.name,
            "modello": "",
            "stato": stato_da_eta(ts),
            "ultima_attivita": ora_iso(ts),
            "ultimo_messaggio": (ultimo_prompt or "")[:240],
            "id": f.stem,
            "interna": False,
        })
    return sessioni, f"{len(sessioni)} trascrizioni in {radice}"


def claude_remoto():
    # si usa la più recente tra la copia accanto allo script e quella nella cartella condivisa
    candidati = [QUI / "claude_remoto.json"] + ([CONDIVISA / "claude_remoto.json"] if CONDIVISA else [])
    esistenti = [p for p in candidati if p.exists()]
    if not esistenti:
        return [], "istantanea assente: chiedi a Claude di rigenerare claude_remoto.json"
    p = max(esistenti, key=lambda x: x.stat().st_mtime)
    try:
        dati = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        return [], f"istantanea illeggibile: {e}"
    eta = (time.time() - p.stat().st_mtime) / 60
    return dati.get("sessioni", []), f"istantanea di {eta:.0f} minuti fa ({dati.get('generata', '?')})"


MANUALI = [
    {"strumento": "Cowork", "nota": "non raggiungibile: il filtro per le sessioni Cowork non è disponibile (verificato 2026-10-20)"},
    {"strumento": "ChatGPT", "nota": "nessuna API nota per elencare le chat: controllo manuale"},
]


def altre_macchine():
    """Sessioni esportate da altre macchine nella cartella condivisa."""
    if not CONDIVISA or not CONDIVISA.exists():
        return [], f"cartella condivisa {CONDIVISA} assente: nessuna esportazione"
    sessioni, note = [], []
    for p in sorted(CONDIVISA.glob("*.json")):
        if p.name == "claude_remoto.json" or p.stem.upper() == MACCHINA:
            continue
        try:
            dati = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            note.append(f"{p.stem}: illeggibile ({e})")
            continue
        chi = str(dati.get("macchina") or "").upper()
        if chi == MACCHINA:
            continue  # copia di conflitto di OneDrive del proprio file (es. MANAS-Dedalo.json)
        if chi != p.stem.upper():
            note.append(f"{p.name}: ignorato, contiene dati di {chi or '?'} (copia di conflitto della sincronizzazione?)")
            continue
        eta = (time.time() - p.stat().st_mtime) / 60
        vecchia = eta > VECCHIA_SE_MINUTI
        for s in dati.get("sessioni", []):
            s = dict(s, macchina=chi, interna=False, ultimo_messaggio="", cartella="")
            if vecchia and s.get("stato") in ("attiva", "in lavoro"):
                s["stato"] = "sconosciuto"  # esportazione ferma: lo stato non è più affidabile
            sessioni.append(s)
        note.append(f"{p.stem}: aggiornata {eta:.0f} min fa" + (" ⚠ esportazione ferma?" if vecchia else ""))
    return sessioni, "; ".join(note) or "nessuna altra macchina"


def raccogli_locali():
    """Fonti di questa macchina, ognuna isolata: una fonte rotta non ferma le altre."""
    fonti, tutte = {}, []
    for nome, fn in (("Codex", codex), ("Claude locale", claude_locale)):
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
    limite = datetime.fromtimestamp(time.time() - 30 * 86400, timezone.utc).isoformat()
    scelte = [{k: s.get(k) for k in CAMPI_ESPORTATI} for s in tutte
              if not s.get("interna") and (s.get("ultima_attivita") or "") >= limite]
    dest = CONDIVISA / f"{MACCHINA}.json"
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps({"macchina": MACCHINA, "generata": ora_iso(time.time()), "sessioni": scelte},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, dest)  # sostituzione in un colpo: chi legge non vede mai un file a metà
    return dest, len(scelte)


def raccogli():
    fonti, tutte = raccogli_locali()
    for nome, fn in (("Claude remoto", claude_remoto), ("Altre macchine", altre_macchine)):
        try:
            s, nota = fn()
        except Exception as e:
            s, nota = [], f"errore: {e}"
        fonti[nome] = {"n": len(s), "nota": nota}
        tutte.extend(s)
    # una sessione locale collegata in remote control compare anche nell'istantanea remota: si tiene quella remota
    remoti = {s["titolo"] for s in tutte if s["strumento"] == "Claude (remoto)"}
    tutte = [s for s in tutte if not (s["strumento"] == "Claude Code" and s["titolo"] in remoti)]
    tutte.sort(key=lambda s: s.get("ultima_attivita") or "", reverse=True)
    return {"generato": ora_iso(time.time()), "fonti": fonti, "manuali": MANUALI, "sessioni": tutte}


class Gestore(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/sessioni"):
            corpo, tipo = json.dumps(raccogli(), ensure_ascii=False).encode("utf-8"), "application/json"
        elif self.path in ("/", "/index.html"):
            corpo, tipo = (QUI / "index.html").read_bytes(), "text/html"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Dashboard sessioni Claude e Codex")
    ap.add_argument("--esporta", action="store_true", help="scrive l elenco sessioni nella cartella condivisa")
    ap.add_argument("--ogni", type=int, default=0, help="con --esporta: ripete ogni N secondi (0 = una volta)")
    a = ap.parse_args()
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
        # su Windows il riuso dell'indirizzo lascerebbe partire due dashboard sulla stessa porta senza errore
        ThreadingHTTPServer.allow_reuse_address = False
        try:
            server = ThreadingHTTPServer(("127.0.0.1", PORTA), Gestore)
        except OSError:
            raise SystemExit(f"Porta {PORTA} occupata: la dashboard è forse già avviata. Apri http://127.0.0.1:{PORTA}")
        print(f"Dashboard {MACCHINA} su http://127.0.0.1:{PORTA}  (Ctrl+C per fermare)")
        server.serve_forever()
