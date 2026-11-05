"""Test della dashboard con soli dati finti.  Avvio:  cd dashboard && python -m unittest -v"""
import http.client
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))

import collegamenti as col  # noqa: E402
import dashboard as d  # noqa: E402
import organizza as org  # noqa: E402


def op(ts, n, nome_op, **campi):
    return dict(campi, ts=ts, n=n, op=nome_op)


class TestCollegamenti(unittest.TestCase):
    def test_riferimenti_da_testo(self):
        t = ("vedi session_01AbCdEfGh e https://github.com/esempio/sito/pull/12, anche esempio/sito#12 "
             "e 0f8fad5b-d9cb-469f-a165-70867728950e")
        r = col.riferimenti_da_testo(t)
        self.assertIn("session_01AbCdEfGh", r)
        self.assertIn("pr:esempio/sito#12", r)
        self.assertEqual(r.count("pr:esempio/sito#12"), 1)  # stessa PR in due forme: una volta sola
        self.assertIn("0f8fad5b-d9cb-469f-a165-70867728950e", r)

    def test_chiave_cartella_uguale_tra_macchine(self):
        self.assertEqual(col.chiave_cartella("C:\\Onedrive\\_ELE\\Vivaio\\"), col.chiave_cartella("c:/onedrive/_ele/vivaio"))
        self.assertNotEqual(col.chiave_cartella("C:\\a"), col.chiave_cartella("C:\\b"))
        self.assertEqual(col.nome_progetto("repo esempio/sito"), "esempio/sito")
        self.assertEqual(col.nome_progetto("C:\\x\\vivaio"), "vivaio")

    def base(self):
        return [
            {"id": "a", "titolo": "Schede vivaio legenda", "ultima_attivita": "2026-11-04T10:00:00+00:00",
             "cartella": "C:\\p\\vivaio"},
            {"id": "b", "titolo": "Schede vivaio stampa", "ultima_attivita": "2026-11-04T11:00:00+00:00",
             "cartella": "C:\\p\\vivaio", "genitore": "a"},
            {"id": "c", "titolo": "Calendario semine", "ultima_attivita": "2026-11-04T09:00:00+00:00",
             "riferimenti": ["b", "pr:o/r#1"]},
            {"id": "e", "titolo": "Altro tema", "ultima_attivita": "2026-11-04T12:00:00+00:00",
             "riferimenti": ["pr:o/r#1"]},
        ]

    def test_tipi_di_arco(self):
        s = [col.arricchisci(x) for x in self.base()]
        archi = {a["id"]: a for a in col.archi_automatici(s)}
        self.assertEqual(archi["padre:a>b"]["confidenza"], "certo")
        self.assertIn("cita:c>b", archi)               # orientato dal più vecchio al più recente
        self.assertIn("stessa_pr:c>e", archi)
        self.assertIn("stessa_cartella:a>b", archi)
        self.assertEqual(archi["simile:a>b"]["confidenza"], "proposta")
        self.assertFalse(any(a["tipo"] == "simile" and "c" in (a["da"], a["a"]) for a in archi.values()))
        auto = col.gruppi_automatici(s)
        self.assertEqual([g["membri"] for g in auto], [["a", "b"]])

    def test_soglia_somiglianza(self):
        s = [col.arricchisci(x) for x in self.base()]
        alta = col.archi_automatici(s, soglia=0.99, soglia_vicine=0.99)
        self.assertFalse(any(a["tipo"] == "simile" for a in alta))

    def test_rifiuto_non_ricompare_e_conferma(self):
        s = [col.arricchisci(x) for x in self.base()]
        archi = col.archi_automatici(s)
        out = col.applica_decisioni(archi, [{"id": "dipende_da:c>a", "da": "c", "a": "a", "tipo": "dipende_da"}],
                                    {"simile:a>b": "rifiuta", "cita:c>b": "conferma"})
        ids = {a["id"]: a for a in out}
        self.assertNotIn("simile:a>b", ids)
        self.assertEqual(ids["cita:c>b"]["confidenza"], "confermato")
        self.assertEqual(ids["dipende_da:c>a"]["confidenza"], "manuale")


class TestOrganizza(unittest.TestCase):
    def test_fusione_deterministica_e_ultima_scrittura(self):
        manas = [op("2026-11-03T09:00:00+00:00", 1, "crea_gruppo", id="g1", nome="Uno", macchina="MANAS"),
                 op("2026-11-03T10:00:00+00:00", 2, "rinomina_gruppo", id="g1", nome="manas", macchina="MANAS")]
        dedalo = [op("2026-11-03T11:00:00+00:00", 1, "rinomina_gruppo", id="g1", nome="dedalo", macchina="DEDALO"),
                  op("2026-11-03T08:00:00+00:00", 2, "aggiungi", sessione="s1", gruppo="g1", macchina="DEDALO")]
        a = org.fondi(manas + dedalo)
        b = org.fondi(list(reversed(dedalo + manas)))
        self.assertEqual(a, b)
        self.assertEqual(a["gruppi"]["g1"]["nome"], "dedalo")
        # l'aggiunta di dedalo è più vecchia della creazione del gruppo: il gruppo non esisteva ancora
        self.assertNotIn("s1", a["membri"])

    def test_sottogruppi_senza_cicli_ed_eliminazione(self):
        ops = [op("1", 1, "crea_gruppo", id="a", nome="A"), op("1", 2, "crea_gruppo", id="b", nome="B", genitore="a"),
               op("1", 3, "crea_gruppo", id="c", nome="C", genitore="b"), op("1", 4, "aggiungi", sessione="s", gruppo="c"),
               op("2", 1, "sposta_gruppo", id="a", genitore="c")]  # ciclo: ignorato
        st = org.fondi(ops)
        self.assertEqual(st["gruppi"]["a"]["genitore"], "")
        self.assertEqual(org.percorso_gruppo(st["gruppi"], "c"), "A › B › C")
        self.assertEqual(org.discendenti(st["gruppi"], "a"), {"a", "b", "c"})
        st = org.fondi(ops + [op("3", 1, "elimina_gruppo", id="b")])
        self.assertEqual(st["gruppi"]["c"]["genitore"], "a")
        self.assertEqual(st["membri"]["s"], "c")
        st = org.fondi(ops + [op("3", 1, "elimina_gruppo", id="c")])
        self.assertEqual(st["membri"]["s"], "b")

    def test_regole(self):
        st = org.fondi([op("1", 1, "crea_gruppo", id="g", nome="G"),
                        op("1", 2, "crea_regola", id="r", campo="titolo", contiene="Vivaio", gruppo="g")])
        self.assertEqual(org.gruppo_da_regole({"titolo": "schede VIVAIO"}, st["regole"]), "g")
        self.assertIsNone(org.gruppo_da_regole({"titolo": "altro"}, st["regole"]))

    def test_validazione(self):
        for cattiva in ({"op": "sconosciuta"}, {"op": "collega", "da": "a", "a": "a", "tipo": "dipende_da"},
                        {"op": "collega", "da": "a", "a": "b", "tipo": "inventato"},
                        {"op": "imposta", "sessione": "s", "campo": "password", "valore": "x"},
                        {"op": "crea_gruppo", "id": "../../x", "nome": "n"},
                        {"op": "imposta", "sessione": "s", "campo": "nota", "valore": "x" * 3000}):
            with self.assertRaises(org.OperazioneNonValida):
                org.valida(cattiva)
        self.assertEqual(org.valida({"op": "togli", "sessione": "s", "extra": "via"}), {"op": "togli", "sessione": "s"})

    def test_scrittura_atomica_e_conflitti(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            org.aggiungi_operazioni(tmp, "MANAS", [{"op": "crea_gruppo", "id": "g", "nome": "G"}])
            org.aggiungi_operazioni(tmp, "MANAS", [{"op": "aggiungi", "sessione": "s", "gruppo": "g"}])
            self.assertEqual([p.name for p in tmp.iterdir()], ["organizza-MANAS.json"])  # nessun .tmp residuo
            dati = json.loads((tmp / "organizza-MANAS.json").read_text(encoding="utf-8"))
            self.assertEqual([o["n"] for o in dati["operazioni"]], [1, 2])
            (tmp / "organizza-MANAS-Dedalo.json").write_text(json.dumps(
                {"macchina": "MANAS", "operazioni": [{"op": "togli", "sessione": "s", "ts": "9", "n": 1}]}), encoding="utf-8")
            ops, note = org.leggi_registri([tmp])
            self.assertEqual(org.fondi(ops)["membri"], {"s": "g"})
            self.assertTrue(any("conflitto" in n for n in note))
        finally:
            shutil.rmtree(tmp)


class TestDemoEServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        d.attiva_demo()
        d.DEMO_SCRITTURE = cls.tmp
        cls.server = d.crea_server(0)
        d.PORTA = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp)

    def richiesta(self, metodo, percorso, corpo=None, intestazioni=None):
        c = http.client.HTTPConnection("127.0.0.1", d.PORTA, timeout=10)
        h = {"Content-Type": "application/json"}
        h.update(intestazioni or {})
        c.request(metodo, percorso, body=json.dumps(corpo) if corpo is not None else None, headers=h)
        r = c.getresponse()
        return r.status, r.read().decode("utf-8")

    def test_grafo_demo(self):
        stato, testo = self.richiesta("GET", "/api/grafo")
        self.assertEqual(stato, 200)
        g = json.loads(testo)
        ids = [s["id"] for s in g["sessioni"]]
        self.assertGreaterEqual(len(ids), 35)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("demo-conflitto-0001", ids)
        self.assertNotIn("demo-proprio-0001", ids)
        gruppi = {x["id"]: x for x in g["gruppi"]}
        self.assertEqual(gruppi["g-clienti"]["nome"], "Clienti 2026")       # vince dedalo (più recente)
        self.assertEqual(gruppi["g-schede"]["percorso"], "Clienti 2026 › Vivaio › Schede")
        s = {x["id"]: x for x in g["sessioni"]}
        self.assertEqual(s["demo-claude-0001"]["nota"], "Usare la palette verde approvata")
        self.assertEqual(s["session_demo_r003"]["gruppo_fonte"], "regola")
        self.assertEqual(s["demo-dedalo-0001"]["stato"], "sconosciuto")    # esportazione vecchia
        self.assertNotIn("simile:demo-claude-0005>demo-dedalo-0008", {a["id"] for a in g["archi"]})
        tipi = {a["tipo"] for a in g["archi"]}
        self.assertTrue({"padre", "cita", "stessa_pr", "stessa_cartella", "simile", "dipende_da"} <= tipi)
        stati = {x["stato"] for x in g["sessioni"]}
        self.assertTrue({"attiva", "in lavoro", "bloccata", "interrotta", "ferma", "completata", "archiviata",
                         "sconosciuto", "fallita", "offline"} <= stati)
        self.assertTrue({"bloccata", "contesto", "doppia", "esportazione_ferma", "fallita", "orfana"}
                        <= {a["tipo"] for a in g["avvisi"]})

    def test_scrittura_e_rilettura(self):
        stato, _ = self.richiesta("POST", "/api/organizza", {"operazioni": [
            {"op": "crea_gruppo", "id": "g-test", "nome": "Prova", "genitore": "g-interno"},
            {"op": "aggiungi", "sessione": "demo-codex-0003", "gruppo": "g-test"}]},
            {"Origin": f"http://127.0.0.1:{d.PORTA}"})
        self.assertEqual(stato, 200)
        g = json.loads(self.richiesta("GET", "/api/grafo")[1])
        s = {x["id"]: x for x in g["sessioni"]}
        self.assertEqual(s["demo-codex-0003"]["gruppo_percorso"], "Interno › Prova")
        self.assertTrue((self.tmp / "organizza-DEMO.json").exists())
        stato, md = self.richiesta("GET", "/api/esporta.md?gruppo=g-interno")
        self.assertEqual(stato, 200)
        self.assertIn("Script di conversione delle mappe", md)

    def test_scritture_rifiutate(self):
        buona = {"operazioni": [{"op": "togli", "sessione": "x"}]}
        self.assertEqual(self.richiesta("POST", "/api/organizza", buona, {"Origin": "http://esempio.com"})[0], 403)
        self.assertEqual(self.richiesta("POST", "/api/organizza", buona, {"Host": "attaccante.example"})[0], 403)
        self.assertEqual(self.richiesta("POST", "/api/organizza", buona, {"Content-Type": "text/plain"})[0], 403)
        self.assertEqual(self.richiesta("POST", "/api/organizza", {"operazioni": [{"op": "boh"}]})[0], 400)
        self.assertEqual(self.richiesta("POST", "/api/organizza", {"operazioni": []})[0], 400)
        self.assertEqual(self.richiesta("GET", "/../dashboard.py")[0], 404)
        self.assertEqual(self.richiesta("GET", "/api/esporta.md?gruppo=inesistente")[0], 404)


class TestFontiLocaliFinte(unittest.TestCase):
    """Lettura di ~/.claude su una home finta (formato ipotizzato, da confermare con sonda.py)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.salvati = (d.HOME, d.DEMO, d.CONDIVISA, d.MACCHINA)
        d.HOME, d.DEMO, d.CONDIVISA, d.MACCHINA = self.tmp / "home", False, self.tmp / "condivisa", "PROVA"
        prog = d.HOME / ".claude" / "projects" / "C--progetti-vivaio"
        (prog / "aaaaaaaa-1111-4111-8111-111111111111" / "subagents").mkdir(parents=True)
        madre = prog / "aaaaaaaa-1111-4111-8111-111111111111.jsonl"
        altra = prog / "bbbbbbbb-2222-4222-8222-222222222222.jsonl"
        righe = [{"type": "user", "timestamp": "2026-11-04T08:00:00Z", "cwd": "C:\\progetti\\vivaio",
                  "sessionId": "aaaaaaaa-1111-4111-8111-111111111111", "message": {"content": "Prima richiesta"}},
                 {"type": "custom-title", "customTitle": "Schede vivaio"},
                 {"type": "assistant", "message": {"content": "vedi bbbbbbbb-2222-4222-8222-222222222222, "
                                                              "session_01XyZaBcDeF e github.com/o/r/pull/7"}}]
        madre.write_text("\n".join(json.dumps(r) for r in righe) + "\n", encoding="utf-8")
        altra.write_text(json.dumps({"type": "custom-title", "customTitle": "Altra"}) + "\n" * 2, encoding="utf-8")
        (prog / "aaaaaaaa-1111-4111-8111-111111111111" / "subagents" / "agent-1.jsonl").write_text(
            json.dumps({"type": "user", "cwd": "C:\\progetti\\vivaio", "message": {"content": "sotto-compito"}}) + "\n" * 2,
            encoding="utf-8")

    def tearDown(self):
        d.HOME, d.DEMO, d.CONDIVISA, d.MACCHINA = self.salvati
        shutil.rmtree(self.tmp)

    def crea_codex(self):
        """state_5.sqlite finto con le colonne viste dalla sonda il 2026-11-05 (solo quelle usate)."""
        import sqlite3
        db = d.HOME / ".codex" / "state_5.sqlite"
        db.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(db)
        c.execute("create table threads (id text, rollout_path text, cwd text, title text, name text, model text,"
                  " originator text, thread_source text, archived integer, updated_at_ms integer, tokens_used integer,"
                  " created_at_ms integer, attached_thread_parent_id text, thread_section_id text, project_id text)")
        c.execute("create table thread_sections (id text, name text, appearance text)")
        c.execute("create table projects (id text, name text)")
        c.execute("insert into thread_sections values ('sez1', 'In corso', '')")
        c.execute("insert into projects values ('prg1', 'Preventivi')")
        c.execute("insert into projects values ('prg2', 'Vivaio')")
        c.execute("create table project_roots (project_id text, position integer, path text)")
        c.execute("insert into project_roots values ('prg2', 0, 'C:\\Progetti')")
        c.execute("insert into project_roots values ('prg2', 1, 'C:\\Progetti\\vivaio')")
        c.execute("create table thread_spawn_edges (parent_thread_id text, child_thread_id text, status text)")
        c.execute("create table remote_control_enrollments (server_name text, remote_control_enabled integer, updated_at integer)")
        t = 1_700_000_000_000
        righe = [(f"g{i}", "", "C:\\p", "Guardian review", None, "m", "Codex Desktop", "guardian_review", 0, t + 1000 + i, 0, t, None,
                  None, None) for i in range(100)]
        righe += [("madre", "", "C:\\p", "Lavoro vero", None, "m", "Codex Desktop", "user", 0, t + 10, 0, t, None, "sez1", "prg1"),
                  ("figlio", "", "C:\\p", "Sottoagente", None, "m", "Codex Desktop", "subagent", 0, t + 20, 0, t + 5, None, None, None),
                  ("allegato", "", "C:\\p", "Allegato", None, "m", "Codex Desktop", "user", 0, t + 30, 0, t + 6, "madre", "sez1", None),
                  ("dentro", "", "c:\\progetti\\VIVAIO\\schede", "Dentro", None, "m", "Codex Desktop", "user", 0, t + 40, 0, t, None, None, None),
                  ("simile", "", "C:\\Progetti-vecchi", "Fuori", None, "m", "Codex Desktop", "user", 0, t + 41, 0, t, None, None, None)]
        c.executemany("insert into threads values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", righe)
        c.execute("insert into thread_spawn_edges values ('madre', 'figlio', 'x')")
        c.commit()
        c.close()

    def test_codex_genitori_e_guardian_non_escludono_i_thread_veri(self):
        self.crea_codex()
        sessioni, nota = d.codex()
        s = {x["id"]: x for x in sessioni}
        self.assertTrue({"madre", "figlio", "allegato"} <= set(s), nota)  # non esclusi dalle 100 revisioni guardian
        self.assertEqual(sum(1 for x in sessioni if x["interna"]), d.MAX_GUARDIAN)
        self.assertEqual(s["figlio"]["genitore"], "madre")       # da thread_spawn_edges
        self.assertEqual(s["allegato"]["genitore"], "madre")     # da attached_thread_parent_id
        self.assertIsNone(s["madre"]["genitore"])
        self.assertTrue(s["madre"]["inizio"].startswith("2023-11-14"))
        self.assertEqual((s["madre"]["sezione_codex"], s["madre"]["progetto_codex"]), ("In corso", "Preventivi"))
        self.assertIsNone(s["figlio"]["sezione_codex"])
        self.assertEqual(s["dentro"]["progetto_codex"], "Vivaio")   # dalla cartella del progetto (project_roots)
        self.assertIsNone(s["simile"]["progetto_codex"])           # "Progetti-vecchi" non è dentro "Progetti"
        self.assertIsNone(s["figlio"]["progetto_codex"])
        for x in sessioni:
            x["macchina"] = "PROVA"
        auto = {g["nome"]: g for g in col.gruppi_automatici([col.arricchisci(x) for x in sessioni])}
        self.assertEqual(auto["🗂 In corso"]["membri"], ["allegato", "madre"])
        self.assertEqual(auto["🧭 Preventivi"]["nome_proposto"], "Preventivi")

    def test_sonda_non_stampa_contenuti(self):
        import contextlib
        import io
        import sonda
        self.crea_codex()
        sonda.HOME = d.HOME
        uscita = io.StringIO()
        with contextlib.redirect_stdout(uscita):
            sonda.sonda_codex()
        testo = uscita.getvalue()
        self.assertIn("spawn_edges: figli presenti in threads: 1", testo)
        self.assertIn("attached_thread_parent_id presente in threads: 1", testo)
        for segreto in ("Lavoro vero", "Sottoagente", "C:\\\\p", "madre"):
            self.assertNotIn(segreto, testo)

    def test_coda_scarta_solo_la_riga_tagliata(self):
        p = self.tmp / "f.jsonl"
        p.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
        self.assertEqual(d.coda_file(p), [{"a": 1}, {"b": 2}])             # file corto: tutte le righe
        p.write_text('{"x": "' + "y" * 100 + '"}\n{"c": 3}\n', encoding="utf-8")
        self.assertEqual(d.coda_file(p, byte=20), [{"c": 3}])              # riga tagliata scartata

    def test_claude_locale_subagenti_citazioni_esportazione(self):
        sessioni, _ = d.claude_locale()
        d.prepara(sessioni)
        s = {x["id"]: x for x in sessioni}
        madre = s["aaaaaaaa-1111-4111-8111-111111111111"]
        self.assertEqual(madre["titolo"], "Schede vivaio")
        self.assertTrue(madre["inizio"].startswith("2026-11-04T08:00:00"))
        self.assertIn("bbbbbbbb-2222-4222-8222-222222222222", madre["riferimenti"])  # UUID risolto: sessione nota
        self.assertIn("session_01XyZaBcDeF", madre["riferimenti"])
        self.assertIn("pr:o/r#7", madre["riferimenti"])
        self.assertNotIn("aaaaaaaa-1111-4111-8111-111111111111", madre["riferimenti"])  # non cita sé stessa
        self.assertEqual(s["agent-1"]["genitore"], "aaaaaaaa-1111-4111-8111-111111111111")
        self.assertEqual(s["agent-1"]["tipo"], "subagente")
        self.assertEqual(madre["progetto"], "vivaio")
        dest, n = d.esporta()
        dati = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(n, 3)
        for x in dati["sessioni"]:
            self.assertEqual(set(x), set(d.CAMPI_ESPORTATI))   # niente cartella, messaggi o altro
        self.assertNotIn("C:\\\\progetti", dest.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
