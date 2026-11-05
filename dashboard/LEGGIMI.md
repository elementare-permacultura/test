# Dashboard sessioni (prototipo, aggiornato 2026-11-05)

Mostra in una pagina locale le sessioni di Claude Code (locali, Remote Control, cloud) e Codex delle macchine manas e dedalo.
Le collega tra loro, le organizza in gruppi e sottogruppi e le presenta in 8 viste.
Serve solo Python 3.12 o successivo (libreria standard, nessuna dipendenza). Il browser non scarica librerie esterne.

- **Lettura:** solo file locali, mai credenziali (`~/.codex/auth.json` escluso).
- **Scrittura:** solo in due casi:
  - con `--esporta`, in `<CONDIVISA>/<MACCHINA>.json`;
  - quando organizzi le sessioni dalla pagina, in `<CONDIVISA>/organizza-<MACCHINA>.json`.

## Avvio

- **Windows:** doppio clic su `AVVIA_DASHBOARD.bat`. Avvia l'esportazione (finestra ridotta, ogni 60 s), la dashboard e il browser.
- **A mano:** `python dashboard.py`, poi http://127.0.0.1:8765 (solo locale, si aggiorna ogni 30 s).
- **Porta diversa:** variabile `PORT`. Se la porta è occupata la dashboard non parte e lo dice.
- **Esportazione per le altre macchine:** `python dashboard.py --esporta [--ogni 60]`.
- **Cartella condivisa:** variabile `DASHBOARD_CONDIVISA`, altrimenti `dati\` accanto allo script.
- **Sonda dei formati:** `python sonda.py`. Stampa solo nomi di campi e conteggi, mai contenuti. Serve a confermare le ipotesi elencate sotto.
- **Test:** `cd dashboard` poi `python -m unittest -v` (17 test, solo dati finti).

## Le 8 viste

| Vista | Cosa mostra | Cosa si può fare |
|---|---|---|
| Tabella | tutte le sessioni, con gruppo, etichette, prossima azione | selezione multipla: sposta, nuovo gruppo, collega in ordine di tempo, etichetta, nascondi |
| Grafo a livelli | catene da sinistra a destra; una fascia colorata per gruppo | zoom (rotella, ＋/－, Adatta), trascina lo sfondo, clic su un nodo |
| Grafo a forze | i nodi si dispongono da soli; riempimento = stato, bordo = gruppo | trascina i nodi, Pausa, Rimescola |
| Albero | gruppi → sottogruppi → sessioni → sessioni figlie | crea, rinomina, elimina; trascina sessioni e gruppi oppure usa i menu “Sposta” (sul telefono); Markdown del gruppo |
| Proposte | gruppi automatici per cartella e collegamenti da confermare | conferma o rifiuta (anche in blocco), crea regole, annulla decisioni |
| Cronologia | barre dall'inizio all'ultima attività | corsie per macchina o per gruppo, periodo 24 h / 7 g / 30 g |
| Kanban | colonne da fare / in corso / in attesa / fatto (modificabili) | trascina le carte oppure usa il menu |
| Avvisi | situazioni da guardare | clic sulla sessione |

Comuni a tutte le viste:
- **Filtri:** ricerca, macchina, gruppo (sottogruppi compresi), revisioni guardian, sessioni ferme, nascoste.
- **Tema:** chiaro, scuro o automatico.
- **Pannello dettagli:** si apre con un clic su una sessione. Contiene nota, prossima azione, etichette, priorità, colonna, gruppo, collegamenti in entrata e in uscita (con conferma, rifiuto e scollegamento) e "Collega a…". Per gli id `session_…` c'è il link "apri in claude.ai".
- **Markdown di un gruppo:** `/api/esporta.md?gruppo=<id>`, da incollare in una nuova chat per passarle il contesto.

## Collegamenti automatici

| Tipo | Da dove | Confidenza |
|---|---|---|
| genitore → figlio | campo `genitore`: subagenti di Claude, sottosessioni | certo |
| cita | una sessione contiene l'id di un'altra (`session_…` o UUID di una sessione nota) | probabile |
| stessa PR | due sessioni citano la stessa pull request | probabile |
| stessa cartella | stessa impronta di cartella; archi solo tra sessioni consecutive, più un gruppo automatico per cartella | probabile |
| titoli simili | somiglianza dei titoli ≥ 50%, oppure ≥ 25% nello stesso progetto entro 2 ore | da confermare |

- **Gruppi proposti** (vista Proposte, "Crea gruppo" li trasforma in gruppi tuoi):
  - una cartella con almeno due sessioni;
  - ogni **sezione** e ogni **progetto** che hai già creato in Codex. Le sezioni con lo stesso nome su macchine diverse diventano un'unica proposta.

  Le sessioni che hai già messo a mano in un gruppo non vengono spostate.
- **Collegamenti manuali:** "prerequisito di", "continua in", "duplicato di", "correlata a".
- **Decisioni sulle proposte:**
  - una proposta rifiutata non ricompare;
  - una proposta confermata diventa "confermato";
  - una decisione si può annullare.

## Organizzazione condivisa tra le macchine

- Ogni macchina scrive solo il proprio `organizza-<MACCHINA>.json`, quindi OneDrive non crea copie di conflitto.
- Alla lettura la dashboard fonde i registri di tutte le macchine in ordine di orario: in caso di conflitto vince la modifica più recente, e il risultato è lo stesso su ogni macchina.
- Un file come `organizza-MANAS-Dedalo.json`, cioè una copia di conflitto, viene ignorato e segnalato tra le fonti.

```json
{"macchina": "MANAS", "operazioni": [{"ts": "ISO", "n": 1, "op": "crea_gruppo", "id": "g-…", "nome": "Clienti"}]}
```

Operazioni ammesse, controllate su un elenco chiuso:
- **gruppi:** `crea_gruppo`, `rinomina_gruppo`, `sposta_gruppo` (gruppo dentro gruppo = sottogruppo, senza cicli), `elimina_gruppo` (sessioni e sottogruppi passano al gruppo superiore);
- **membri:** `aggiungi`, `togli`;
- **collegamenti:** `collega`, `scollega`;
- **proposte:** `conferma`, `rifiuta`, `annulla_decisione`;
- **attributi:** `imposta` (nota, prossima_azione, etichette, priorita, colonna, nascosta), `imposta_colonne`;
- **regole:** `crea_regola`, `elimina_regola`. Esempio: “se il titolo contiene X → gruppo Y”. Valgono per le sessioni senza un gruppo manuale.

## Avvisi

- sessione bloccata (oltre 2 h diventa "attenzione");
- ultimo turno fallito;
- contesto oltre l'80%, letto da messaggi come “contesto 870k/1M”;
- stessa sessione attiva su più macchine;
- esportazione di un'altra macchina ferma;
- sessione in nessun gruppo da più di 7 giorni;
- proposte in attesa.

## Modalità dimostrativa

```
python dashboard.py --demo
```

- **Cosa legge:** solo `esempi/`. Non apre `~/.codex` né `~/.claude`.
- **Dove scrive:** le modifiche alla pagina vanno in `demo-scritture/` (ignorata da git). Cancellarla riporta la demo allo stato iniziale.
- **Macchina locale:** si chiama `DEMO`.
- **Esportazione:** `--demo --esporta` viene rifiutato.
- **Orari:** negli esempi sono riferiti a 2026-11-04 12:00 UTC e vengono spostati su adesso.

| File | Contenuto |
|---|---|
| `esempi/locale/sessioni.json` | 13 sessioni della macchina DEMO, con subagenti, citazioni e una revisione guardian |
| `esempi/claude_remoto.json` | 9 sessioni remote, con una sottosessione e citazioni di PR |
| `esempi/MANAS.json` | esportazione fresca, con una sessione ripresa anche su DEMO |
| `esempi/DEDALO.json` | esportazione vecchia (40 min): stati attivi → sconosciuto |
| `esempi/MANAS-Dedalo.json`, `esempi/DEMO.json` | copia di conflitto e file della macchina stessa: ignorati |
| `esempi/organizza-MANAS.json`, `esempi/organizza-DEDALO.json` | gruppi a 3 livelli, note, regola, rifiuto; un conflitto di nome risolto dalla modifica più recente |
| `esempi/organizza-MANAS-Dedalo.json` | copia di conflitto del registro: ignorata |

Prova facoltativa dell'interfaccia (61 controlli, richiede Node e Playwright): `prove/interfaccia.js`, istruzioni in testa al file.

## Formati e API

`GET /api/sessioni`: formato originale, `{"generato", "fonti", "manuali", "sessioni"}`.

`GET /api/grafo` aggiunge `macchina`, `demo`, `gruppi`, `gruppi_auto`, `archi`, `colonne`, `regole`, `decisioni`, `avvisi` e `organizza`.
Ogni sessione ha i campi originali (`strumento`, `tipo`, `titolo`, `modello`, `stato`, `ultima_attivita`, `id`, `macchina`, `interna`, `ultimo_messaggio`, `cartella`) più questi:
- `inizio`, `genitore`, `riferimenti`, `cartella_chiave`, `progetto`, `sezione_codex`, `progetto_codex`;
- se la stessa sessione compare su più macchine: `anche_su`, `attiva_su`;
- dall'organizzazione: `gruppo`, `gruppo_fonte` (manuale/regola), `gruppo_percorso` e gli attributi (`nota`, `prossima_azione`, `etichette`, `priorita`, `colonna`, `nascosta`).

`POST /api/organizza` con `{"operazioni": [...]}` è accettato solo se:
- `Host` è `127.0.0.1:PORT` o `localhost:PORT`;
- `Origin`, se presente, è locale;
- `Content-Type` è `application/json`;
- il corpo è sotto i 64 KB.

Così un sito web aperto nel browser non può scrivere nella dashboard.

`<CONDIVISA>/<MACCHINA>.json`, scritto da `--esporta` in modo atomico:

```json
{"macchina": "MANAS", "generata": "ISO", "sessioni": [{"strumento", "tipo", "titolo", "modello", "stato", "ultima_attivita", "id",
  "inizio", "genitore", "riferimenti", "cartella_chiave", "progetto", "sezione_codex", "progetto_codex"}]}
```

- Niente messaggi né percorsi completi.
- `cartella_chiave` è un'impronta del percorso (sha256, 12 caratteri): permette di riconoscere la stessa cartella su macchine diverse senza mostrarla.
- `progetto` è il nome dell'ultima cartella.
- `riferimenti` contiene solo id di sessione e pull request citati.
- `sezione_codex` e `progetto_codex` sono i nomi che hai dato a sezioni e progetti in Codex.
- Ultimi 30 giorni, senza revisioni guardian. I file del formato precedente (7 campi) continuano a funzionare.
- Un file viene ignorato se `macchina` non coincide con il nome del file oppure se è la macchina stessa. Se è più vecchio di 5 minuti viene segnalato.

## Dati veri

`.gitignore` esclude `dati/`, `claude_remoto.json` e `organizza-*.json` alla radice di `dashboard/`, oltre a `demo-scritture/`, `*.tmp` e le schermate delle prove.
Non aggiungere al repository esportazioni, istantanee o registri reali: contengono titoli e id delle sessioni.

## Formati verificati con `sonda.py` (2026-11-05, una macchina)

Verificato: la sonda stampa solo nomi di campi e conteggi.
- **Claude:**
  - i subagenti stanno in `~/.claude/projects/<progetto>/<sessione>/subagents/*.jsonl`; il genitore è la sessione della cartella;
  - le righe hanno `timestamp`, `cwd`, `gitBranch`, `sessionId`, `isSidechain` e `agentId`.
- **Codex:**
  - in `threads` non c'è `parent_thread_id`;
  - i legami madre-figlia stanno nella tabella `thread_spawn_edges(parent_thread_id, child_thread_id, status)` e nella colonna `threads.attached_thread_parent_id`: la dashboard usa entrambi;
  - l'inizio viene da `created_at_ms`;
  - sezioni e progetti: `threads.thread_section_id` → `thread_sections.name` e `threads.project_id` → `projects.name`;
  - i valori di `thread_source` sono user, subagent, guardian_review, agent_created_thread, chatgpt_handoff, voice_chat e avatar_quick_chat.
- **Revisioni guardian:** sono la maggior parte dei thread (380 su 520). Per questo hanno un limite a parte (`MAX_GUARDIAN` = 20) e non escludono i thread veri (`MAX_THREAD` = 80).

Ancora da verificare con la sonda versione 2:
- il nome del campo del titolo automatico nelle righe `ai-title` di Claude (oggi si provano `aiTitle` e `title`);
- se `guardian_review_feedback.thread_id` collega una revisione guardian al thread revisionato;
- quanti thread usano davvero `thread_section_id` e `project_id` (il collegamento tra id e nome è ricavato dai nomi delle colonne).

## Limiti noti

- I formati dei file Codex e Claude non sono documentati: possono cambiare a ogni aggiornamento.
- "attiva" = attività negli ultimi 3 minuti; per Codex "in lavoro" se l'ultimo turno è iniziato e non concluso, "interrotta?" se è fermo da più tempo.
- Le citazioni tramite UUID si risolvono solo verso sessioni note sulla stessa macchina al momento dell'esportazione. Tra macchine diverse funzionano gli id `session_…` e le pull request.
- La stessa sessione può comparire due volte (locale e remota) quando il titolo locale non coincide. Se l'id è lo stesso, le copie vengono unite e compare "anche su".
- Fuori da `--demo` l'età dei file viene dalla data del file: dipende da come OneDrive la conserva.
- L'ordine delle modifiche tra macchine si basa sugli orologi dei PC: un orologio molto sbagliato può far vincere una modifica più vecchia.
- Il grafo a livelli rompe i cicli ignorando l'arco che entra nella sessione più vecchia del ciclo.
- Il grafo a forze resta fluido fino a qualche centinaio di sessioni visibili; oltre conviene filtrare.
- Su Linux, dopo aver chiuso la dashboard, la stessa porta può restare occupata per circa un minuto (scelta voluta per Windows: due dashboard sulla stessa porta non devono partire).
- Lo stato mostrato è l'ultimo letto, non una prova di attività in tempo reale.
- Provata solo in Linux con Python 3.13, Chromium e dati finti. Windows, Python 3.12, dati veri e OneDrive vanno provati su manas.
