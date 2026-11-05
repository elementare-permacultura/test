"""Organizzazione manuale delle sessioni: registro di operazioni per macchina, fuso alla lettura.

Ogni macchina scrive solo <cartella>/organizza-<MACCHINA>.json, così la sincronizzazione (OneDrive) non crea
copie di conflitto. Alla lettura si fondono i registri di tutte le macchine in ordine (ts, macchina, n): l'ultima
scrittura vince e il risultato è lo stesso su ogni macchina.

Formato del file: {"macchina": "MANAS", "operazioni": [{"ts": ISO, "n": int, "op": nome, ...campi}]}
"""
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

PREFISSO = "organizza-"
TIPI_COLLEGAMENTO = ("dipende_da", "continua", "duplicato", "correlato")
CAMPI_SESSIONE = {"nota": str, "prossima_azione": str, "etichette": list, "priorita": str,
                  "colonna": str, "nascosta": bool}
PRIORITA = ("", "alta", "media", "bassa")
COLONNE_PREDEFINITE = ["da fare", "in corso", "in attesa", "fatto"]
CAMPI_REGOLA = ("titolo", "progetto", "strumento", "macchina")
MAX_TESTO = 2000
MAX_OPERAZIONI = 200
RE_ID = re.compile(r"^[\w:.@|>#-]{1,200}$")  # niente "/" né spazi: gli id non diventano mai percorsi

_blocco = threading.Lock()


class OperazioneNonValida(ValueError):
    pass


def _testo(v, nome, massimo=MAX_TESTO, vuoto=True):
    if not isinstance(v, str):
        raise OperazioneNonValida(f"{nome}: atteso testo")
    v = v.strip()
    if len(v) > massimo:
        raise OperazioneNonValida(f"{nome}: troppo lungo")
    if not vuoto and not v:
        raise OperazioneNonValida(f"{nome}: vuoto")
    return v


def _id(v, nome):
    if not isinstance(v, str) or not RE_ID.match(v):
        raise OperazioneNonValida(f"{nome}: identificativo non valido")
    return v


def valida(op):
    """Controlla un'operazione arrivata dal browser e la riduce ai soli campi ammessi."""
    if not isinstance(op, dict):
        raise OperazioneNonValida("operazione non è un oggetto")
    nome = op.get("op")
    if nome == "crea_gruppo":
        out = {"id": _id(op.get("id"), "id"), "nome": _testo(op.get("nome"), "nome", 120, False)}
        if op.get("genitore"):
            out["genitore"] = _id(op["genitore"], "genitore")
    elif nome == "rinomina_gruppo":
        out = {"id": _id(op.get("id"), "id"), "nome": _testo(op.get("nome"), "nome", 120, False)}
    elif nome == "sposta_gruppo":
        out = {"id": _id(op.get("id"), "id"), "genitore": _id(op["genitore"], "genitore") if op.get("genitore") else ""}
    elif nome == "elimina_gruppo":
        out = {"id": _id(op.get("id"), "id")}
    elif nome == "aggiungi":
        out = {"sessione": _id(op.get("sessione"), "sessione"), "gruppo": _id(op.get("gruppo"), "gruppo")}
    elif nome == "togli":
        out = {"sessione": _id(op.get("sessione"), "sessione")}
    elif nome == "collega":
        if op.get("tipo") not in TIPI_COLLEGAMENTO:
            raise OperazioneNonValida("tipo di collegamento non ammesso")
        out = {"da": _id(op.get("da"), "da"), "a": _id(op.get("a"), "a"), "tipo": op["tipo"]}
        if out["da"] == out["a"]:
            raise OperazioneNonValida("una sessione non si collega a sé stessa")
    elif nome == "scollega":
        out = {"id": _id(op.get("id"), "id")}
    elif nome in ("conferma", "rifiuta", "annulla_decisione"):
        out = {"arco": _id(op.get("arco"), "arco")}
    elif nome == "imposta":
        campo = op.get("campo")
        if campo not in CAMPI_SESSIONE:
            raise OperazioneNonValida("campo non ammesso")
        v = op.get("valore")
        if campo == "etichette":
            if not isinstance(v, list) or len(v) > 20:
                raise OperazioneNonValida("etichette: attesa lista")
            v = [e for e in (_testo(x, "etichetta", 40) for x in v) if e]
        elif campo == "nascosta":
            if not isinstance(v, bool):
                raise OperazioneNonValida("nascosta: atteso vero/falso")
        elif campo == "priorita":
            if v not in PRIORITA:
                raise OperazioneNonValida("priorità non ammessa")
        else:
            v = _testo(v, campo)
        out = {"sessione": _id(op.get("sessione"), "sessione"), "campo": campo, "valore": v}
    elif nome == "imposta_colonne":
        v = op.get("colonne")
        if not isinstance(v, list) or not 1 <= len(v) <= 10:
            raise OperazioneNonValida("colonne: da 1 a 10")
        out = {"colonne": [_testo(x, "colonna", 40, False) for x in v]}
    elif nome == "crea_regola":
        if op.get("campo") not in CAMPI_REGOLA:
            raise OperazioneNonValida("campo della regola non ammesso")
        out = {"id": _id(op.get("id"), "id"), "campo": op["campo"],
               "contiene": _testo(op.get("contiene"), "contiene", 80, False), "gruppo": _id(op.get("gruppo"), "gruppo")}
    elif nome == "elimina_regola":
        out = {"id": _id(op.get("id"), "id")}
    else:
        raise OperazioneNonValida(f"operazione sconosciuta: {nome!r}")
    out["op"] = nome
    return out


# --- lettura e fusione ----------------------------------------------------------------------

def leggi_registri(cartelle):
    """Legge organizza-*.json dalle cartelle date. Ignora file la cui macchina non coincide col nome."""
    operazioni, note = [], []
    for cartella in cartelle:
        if not cartella or not Path(cartella).exists():
            continue
        for p in sorted(Path(cartella).glob(f"{PREFISSO}*.json")):
            atteso = p.stem[len(PREFISSO):].upper()
            try:
                dati = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                note.append(f"{p.name}: illeggibile ({e})")
                continue
            chi = str(dati.get("macchina") or "").upper()
            if chi != atteso:
                note.append(f"{p.name}: ignorato, contiene dati di {chi or '?'} (copia di conflitto?)")
                continue
            n_valide = 0
            for i, op in enumerate(dati.get("operazioni", [])):
                try:
                    v = valida(op)
                except OperazioneNonValida as e:
                    note.append(f"{p.name} #{i}: scartata ({e})")
                    continue
                v.update(ts=str(op.get("ts") or ""), n=int(op.get("n") or i), macchina=chi)
                operazioni.append(v)
                n_valide += 1
            note.append(f"{chi}: {n_valide} operazioni")
    return operazioni, note


def _antenati(gruppi, gid):
    visti = []
    while gid and gid in gruppi and gid not in visti:
        visti.append(gid)
        gid = gruppi[gid].get("genitore") or ""
    return visti


def fondi(operazioni):
    """Applica le operazioni in ordine deterministico e restituisce lo stato dell'organizzazione."""
    stato = {"gruppi": {}, "membri": {}, "collegamenti": {}, "decisioni": {}, "sessioni": {},
             "colonne": list(COLONNE_PREDEFINITE), "regole": {}}
    g, m = stato["gruppi"], stato["membri"]
    for op in sorted(operazioni, key=lambda o: (o.get("ts", ""), o.get("macchina", ""), o.get("n", 0))):
        nome = op["op"]
        if nome == "crea_gruppo":
            gen = op.get("genitore", "")
            if gen and gen not in g:
                gen = ""
            g[op["id"]] = {"id": op["id"], "nome": op["nome"], "genitore": gen}
        elif nome == "rinomina_gruppo" and op["id"] in g:
            g[op["id"]]["nome"] = op["nome"]
        elif nome == "sposta_gruppo" and op["id"] in g:
            gen = op["genitore"]
            # niente cicli: il nuovo genitore non può essere il gruppo stesso o un suo discendente
            if not gen or (gen in g and op["id"] not in _antenati(g, gen)):
                g[op["id"]]["genitore"] = gen
        elif nome == "elimina_gruppo" and op["id"] in g:
            gen = g[op["id"]].get("genitore", "")
            for x in g.values():
                if x.get("genitore") == op["id"]:
                    x["genitore"] = gen
            for s, gid in list(m.items()):
                if gid == op["id"]:
                    if gen:
                        m[s] = gen
                    else:
                        del m[s]
            for r in list(stato["regole"].values()):
                if r["gruppo"] == op["id"]:
                    del stato["regole"][r["id"]]
            del g[op["id"]]
        elif nome == "aggiungi" and op["gruppo"] in g:
            m[op["sessione"]] = op["gruppo"]
        elif nome == "togli":
            m.pop(op["sessione"], None)
        elif nome == "collega":
            cid = f"{op['tipo']}:{op['da']}>{op['a']}"
            stato["collegamenti"][cid] = {"id": cid, "da": op["da"], "a": op["a"], "tipo": op["tipo"]}
        elif nome == "scollega":
            stato["collegamenti"].pop(op["id"], None)
        elif nome in ("conferma", "rifiuta"):
            stato["decisioni"][op["arco"]] = nome
        elif nome == "annulla_decisione":
            stato["decisioni"].pop(op["arco"], None)
        elif nome == "imposta":
            stato["sessioni"].setdefault(op["sessione"], {})[op["campo"]] = op["valore"]
        elif nome == "imposta_colonne":
            stato["colonne"] = op["colonne"]
        elif nome == "crea_regola" and op["gruppo"] in g:
            stato["regole"][op["id"]] = {k: op[k] for k in ("id", "campo", "contiene", "gruppo")}
        elif nome == "elimina_regola":
            stato["regole"].pop(op["id"], None)
    return stato


def gruppo_da_regole(sessione, regole):
    """Primo gruppo la cui regola corrisponde alla sessione (confronto senza maiuscole)."""
    for r in sorted(regole.values(), key=lambda r: r["id"]):
        v = str(sessione.get(r["campo"]) or "").lower()
        if r["contiene"].lower() in v:
            return r["gruppo"]
    return None


def percorso_gruppo(gruppi, gid):
    return " › ".join(gruppi[x]["nome"] for x in reversed(_antenati(gruppi, gid)))


def discendenti(gruppi, gid):
    out = {gid}
    cambiato = True
    while cambiato:
        cambiato = False
        for x in gruppi.values():
            if x.get("genitore") in out and x["id"] not in out:
                out.add(x["id"])
                cambiato = True
    return out


# --- scrittura ------------------------------------------------------------------------------

def aggiungi_operazioni(cartella, macchina, operazioni):
    """Aggiunge operazioni già validate al registro di questa macchina (scrittura atomica)."""
    if not isinstance(operazioni, list) or not 1 <= len(operazioni) <= MAX_OPERAZIONI:
        raise OperazioneNonValida(f"da 1 a {MAX_OPERAZIONI} operazioni")
    valide = [valida(o) for o in operazioni]
    cartella = Path(cartella)
    with _blocco:
        cartella.mkdir(parents=True, exist_ok=True)
        dest = cartella / f"{PREFISSO}{macchina}.json"
        try:
            dati = json.loads(dest.read_text(encoding="utf-8"))
            registro = dati.get("operazioni", []) if str(dati.get("macchina", "")).upper() == macchina else []
        except (OSError, ValueError):
            registro = []
        n = max((int(o.get("n") or 0) for o in registro), default=0)
        ts = datetime.now(timezone.utc).isoformat()
        for v in valide:
            n += 1
            registro.append(dict(v, ts=ts, n=n))
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps({"macchina": macchina, "operazioni": registro}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, dest)
    return len(valide)
