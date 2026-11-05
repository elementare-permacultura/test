"""Sonda della struttura dei dati di Claude Code e Codex su questa macchina (sola lettura).

Stampa SOLO nomi di campi, tipi e conteggi: nessun testo, titolo, percorso o id.
Serve a verificare le ipotesi della dashboard (subagenti, genitori, orari d'inizio) prima di usarle.
Uso:  python sonda.py            poi incolla l'output nella chat.
Versione 2 (2026-11-05): aggiunge chiavi per tipo di riga Claude e controlli sui legami tra thread Codex.
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
    chiavi_per_tipo = {}
    TIPI_SPIATI = ("ai-title", "agent-name", "custom-title", "bridge-session", "last-prompt")
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
                    if o.get("type") in TIPI_SPIATI:
                        chiavi_per_tipo.setdefault(o["type"], Counter()).update(f"{k}:{tipo(v)}" for k, v in o.items())
                    chiavi.update(chiavi_annidate(o))
                    for k in ("isSidechain", "parentUuid", "sessionId", "parentSessionId", "agentId",
                              "timestamp", "cwd", "gitBranch", "leafUuid", "forkedFrom"):
                        if k in o:
                            campi_utili[f"{k}:{tipo(o[k])}" + (f"={o[k]}" if isinstance(o[k], bool) else "")] += 1
        except OSError:
            continue
    print("tipi di riga:", dict(tipi.most_common(30)))
    for t, c in sorted(chiavi_per_tipo.items()):
        print(f"chiavi delle righe {t}: {dict(c)}")
    # nei file dei subagenti, sessionId coincide con la cartella della sessione madre?
    stesso, diverso = 0, 0
    for f in subagenti[:MAX_FILE]:
        try:
            with open(f, encoding="utf-8", errors="replace") as h:
                for riga in h:
                    try:
                        sid = json.loads(riga).get("sessionId")
                    except (ValueError, AttributeError):
                        continue
                    if sid:
                        stesso += sid == f.parent.parent.name
                        diverso += sid != f.parent.parent.name
                        break
        except OSError:
            continue
    print(f"subagenti con sessionId = cartella madre: {stesso}; diverso: {diverso}")
    nomi = Counter("agent-*" if p.stem.startswith("agent-") else "altro" for p in subagenti)
    print(f"nomi dei file subagenti: {dict(nomi)}")
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
            def conta(sql):
                try:
                    return c.execute(sql).fetchone()[0]
                except sqlite3.Error as e:
                    return f"errore: {e}"
            ids = "(select id from threads)"
            controlli = {
                "spawn_edges: genitori presenti in threads": f"select count(*) from thread_spawn_edges where parent_thread_id in {ids}",
                "spawn_edges: figli presenti in threads": f"select count(*) from thread_spawn_edges where child_thread_id in {ids}",
                "attached_thread_parent_id non vuoto": "select count(*) from threads where coalesce(attached_thread_parent_id,'') != ''",
                "attached_thread_parent_id presente in threads": f"select count(*) from threads where attached_thread_parent_id in {ids}",
                "guardian_feedback: thread_id presente in threads": f"select count(*) from guardian_review_feedback where thread_id in {ids}",
                "guardian_feedback: thread_id di thread non guardian": "select count(*) from guardian_review_feedback g join threads t "
                    "on t.id = g.thread_id where coalesce(t.thread_source,'') != 'guardian_review'",
                "guardian_feedback: id presente in threads": f"select count(*) from guardian_review_feedback where id in {ids}",
                "threads con thread_section_id": "select count(*) from threads where coalesce(thread_section_id,'') != ''",
                "threads con project_id": "select count(*) from threads where coalesce(project_id,'') != ''",
                "threads con git_origin_url": "select count(*) from threads where coalesce(git_origin_url,'') != ''",
                "threads con git_branch": "select count(*) from threads where coalesce(git_branch,'') != ''",
                "subagent con genitore in spawn_edges": "select count(*) from threads t join thread_spawn_edges e "
                    "on e.child_thread_id = t.id where t.thread_source = 'subagent'",
                "guardian con genitore in spawn_edges": "select count(*) from threads t join thread_spawn_edges e "
                    "on e.child_thread_id = t.id where t.thread_source = 'guardian_review'",
            }
            for nome, sql in controlli.items():
                print(f"{nome}: {conta(sql)}")
            try:
                stati = c.execute("select status, count(*) from thread_spawn_edges group by status").fetchall()
                print("thread_spawn_edges.status:", dict((str(s), n) for s, n in stati))
            except sqlite3.Error:
                pass
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
