"""Sonda della struttura dei dati di Claude Code e Codex su questa macchina (sola lettura).

Stampa SOLO nomi di campi, tipi e conteggi: nessun testo, titolo, percorso o id.
Serve a verificare le ipotesi della dashboard (subagenti, genitori, orari d'inizio) prima di usarle.
Uso:  python sonda.py            poi incolla l'output nella chat.
"""
import json
import sqlite3
from collections import Counter
from pathlib import Path

HOME = Path.home()
MAX_FILE = 40       # file jsonl esaminati al massimo
MAX_RIGHE = 400     # righe per file


def tipo(v):
    return type(v).__name__


def chiavi_annidate(o, prefisso="", prof=0, out=None):
    out = Counter() if out is None else out
    if isinstance(o, dict) and prof < 3:
        for k, v in o.items():
            nome = f"{prefisso}{k}"
            out[f"{nome}:{tipo(v)}"] += 1
            chiavi_annidate(v, nome + ".", prof + 1, out)
    return out


def sonda_claude():
    radice = HOME / ".claude" / "projects"
    print("== Claude Code:", "presente" if radice.exists() else "assente")
    if not radice.exists():
        return
    principali = list(radice.glob("*/*.jsonl"))
    subagenti = list(radice.glob("*/*/subagents/*.jsonl"))
    altre = Counter(p.relative_to(radice).parts.__len__() for p in radice.rglob("*.jsonl"))
    print(f"file */*.jsonl: {len(principali)}; */*/subagents/*.jsonl: {len(subagenti)}")
    print(f"profondità dei .jsonl (n. parti del percorso → file): {dict(sorted(altre.items()))}")
    tipi, chiavi = Counter(), Counter()
    campi_utili = Counter()
    for f in sorted(principali + subagenti, key=lambda p: p.stat().st_mtime, reverse=True)[:MAX_FILE]:
        try:
            with open(f, encoding="utf-8", errors="replace") as h:
                for i, riga in enumerate(h):
                    if i >= MAX_RIGHE:
                        break
                    try:
                        o = json.loads(riga)
                    except ValueError:
                        continue
                    tipi[str(o.get("type"))] += 1
                    chiavi.update(chiavi_annidate(o))
                    for k in ("isSidechain", "parentUuid", "sessionId", "parentSessionId", "agentId",
                              "timestamp", "cwd", "gitBranch", "leafUuid", "forkedFrom"):
                        if k in o:
                            campi_utili[f"{k}:{tipo(o[k])}" + (f"={o[k]}" if isinstance(o[k], bool) else "")] += 1
        except OSError:
            continue
    print("tipi di riga:", dict(tipi.most_common(30)))
    print("campi utili (presenza):", dict(campi_utili.most_common()))
    print("chiavi più frequenti (prime 60):")
    for k, n in chiavi.most_common(60):
        print(f"  {n:6}  {k}")


def sonda_codex():
    db = HOME / ".codex" / "state_5.sqlite"
    print("== Codex:", "presente" if db.exists() else "assente")
    if not db.exists():
        return
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        tabelle = [r[0] for r in c.execute("select name from sqlite_master where type='table' order by name")]
        for t in tabelle:
            colonne = [f"{r[1]}:{r[2]}" for r in c.execute(f"pragma table_info('{t}')")]
            n = c.execute(f"select count(*) from '{t}'").fetchone()[0]
            print(f"tabella {t} ({n} righe): {', '.join(colonne)}")
        if "threads" in tabelle:
            for campo in ("thread_source", "originator"):
                try:
                    valori = c.execute(f"select {campo}, count(*) from threads group by {campo}").fetchall()
                    # valori di categoria (non testo libero): utili a riconoscere guardian e sottothread
                    print(f"threads.{campo}: {dict((str(v), n) for v, n in valori)}")
                except sqlite3.Error:
                    pass
        c.close()
    except sqlite3.Error as e:
        print("errore sqlite:", e)
    rollout = sorted((HOME / ".codex" / "sessions").rglob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                     reverse=True)[:5] if (HOME / ".codex" / "sessions").exists() else []
    tipi = Counter()
    for f in rollout:
        try:
            with open(f, encoding="utf-8", errors="replace") as h:
                for i, riga in enumerate(h):
                    if i >= MAX_RIGHE:
                        break
                    try:
                        o = json.loads(riga)
                    except ValueError:
                        continue
                    p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
                    tipi[f"{o.get('type')}/{p.get('type')}"] += 1
        except OSError:
            continue
    print(f"rollout esaminati: {len(rollout)}; tipi evento:", dict(tipi.most_common(30)))


if __name__ == "__main__":
    print("Sonda dashboard: solo struttura, nessun contenuto.")
    sonda_claude()
    sonda_codex()
