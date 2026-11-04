# Dashboard sessioni (prototipo, aggiornato 2026-11-04)

Mostra in una pagina locale le sessioni di Claude Code (locali, Remote Control, cloud) e Codex delle macchine manas e dedalo.
Legge in sola lettura e non legge credenziali (`~/.codex/auth.json` escluso). Scrive solo con `--esporta`.
Serve solo Python 3.12 o successivo (libreria standard, nessuna dipendenza).

## Avvio

- Windows: doppio clic su `AVVIA_DASHBOARD.bat`. Avvia l'esportazione (finestra ridotta, ogni 60 s), la dashboard e il browser.
- A mano: `python dashboard.py`, poi http://127.0.0.1:8765 (solo locale, si aggiorna ogni 30 s).
- Porta diversa: variabile `PORT`. Se la porta è occupata la dashboard non parte e lo dice.
- Esportazione per le altre macchine: `python dashboard.py --esporta [--ogni 60]`.
- Cartella condivisa: variabile `DASHBOARD_CONDIVISA`, altrimenti `dati\` accanto allo script.

## Modalità dimostrativa

```
python dashboard.py --demo
```

Legge solo da `esempi/` e non apre `~/.codex` né `~/.claude`. Non legge `claude_remoto.json` né `dati/` accanto allo script.
La macchina locale si chiama `DEMO`. `--demo --esporta` viene rifiutato.

Gli orari negli esempi sono scritti rispetto a 2026-11-04 12:00 UTC. In `--demo` vengono spostati su adesso, così l'età delle sessioni
resta la stessa a ogni avvio. L'età dei file si calcola dal campo `generata`, non dalla data del file.

| File | Contenuto | Cosa deve succedere |
|---|---|---|
| `esempi/locale/sessioni.json` | sessioni della macchina locale DEMO, campi completi | tutte visibili, la revisione guardian solo con il filtro |
| `esempi/claude_remoto.json` | istantanea delle sessioni remote | visibili, senza etichetta @macchina |
| `esempi/MANAS.json` | esportazione fresca (1 min) | stati invariati |
| `esempi/DEDALO.json` | esportazione vecchia (40 min) | segnalata; `attiva` e `in lavoro` diventano `sconosciuto` |
| `esempi/MANAS-Dedalo.json` | copia di conflitto (contiene `MANAS`) | ignorata, con nota |
| `esempi/DEMO.json` | file della macchina stessa | ignorato |

Gli esempi coprono tutti gli stati: attiva, in lavoro, bloccata, interrotta (anche `interrotta?` di Codex), ferma, completata,
archiviata, sconosciuto, fallita, offline. Una sessione locale con lo stesso titolo di una remota mostra il doppione eliminato.
Titoli, cartelle e id sono inventati.

## Formato dei file

`GET /api/sessioni`:

```json
{"generato": "ISO", "fonti": {"nome": {"n": 0, "nota": "testo"}}, "manuali": [{"strumento": "", "nota": ""}], "sessioni": []}
```

Ogni sessione: `strumento`, `tipo`, `titolo`, `modello`, `stato`, `ultima_attivita` (ISO UTC), `id`, `macchina`, `interna` (bool),
`ultimo_messaggio`, `cartella`.

`claude_remoto.json` (istantanea scritta da una sessione Claude con `list_sessions`):

```json
{"generata": "ISO o testo", "sessioni": [ ...sessioni con tutti i campi tranne macchina... ]}
```

`<CONDIVISA>/<MACCHINA>.json` (scritto da `--esporta` in modo atomico, file `.tmp` + `os.replace`):

```json
{"macchina": "MANAS", "generata": "ISO", "sessioni": [{"strumento", "tipo", "titolo", "modello", "stato", "ultima_attivita", "id"}]}
```

Solo questi sette campi: niente messaggi né cartelle. Ultimi 30 giorni, senza revisioni guardian.
Un file viene ignorato se `macchina` non coincide con il nome del file (copie di conflitto di OneDrive, es. `MANAS-Dedalo.json`)
o se è la macchina stessa. Se è più vecchio di 5 minuti viene segnalato e gli stati `attiva`/`in lavoro` diventano `sconosciuto`.

## Fonti

| Fonte | Da dove | Aggiornamento |
|---|---|---|
| Codex della macchina | `~/.codex/state_5.sqlite` (threads, remote_control_enrollments) + coda dei rollout | automatico |
| Claude Code della macchina | `~/.claude/projects/*/*.jsonl` | automatico |
| Claude remoto (cloud, Remote Control) | `claude_remoto.json` (accanto allo script o in `dati\`) | istantanea: va rigenerata |
| Altre macchine | `dati\<MACCHINA>.json`, scritti da `--esporta --ogni 60` | ogni 60 s finché l'esportazione gira |
| Cowork, ChatGPT | — | non raggiungibili, controllo manuale |

## Più macchine (manas + dedalo)

La cartella `C:\Onedrive\_ELE\AI_OFFICINA\dashboard` è sincronizzata su manas e dedalo; su ciascuna basta `AVVIA_DASHBOARD.bat`.
Originale di sviluppo: `C:\OFFICINA_AI\dashboard` su manas.

## Dati veri

`.gitignore` esclude `dati/`, `claude_remoto.json` alla radice di `dashboard/` e i `*.tmp`. Non aggiungere al repository
esportazioni o istantanee reali: contengono titoli e id delle sessioni.

## Limiti noti

- I formati dei file Codex e Claude non sono documentati: possono cambiare a ogni aggiornamento.
- "attiva" = attività negli ultimi 3 minuti; per Codex "in lavoro" se l'ultimo turno è iniziato e non concluso, "interrotta?" se è fermo da più tempo.
- La stessa sessione può comparire due volte (locale e remota) quando il titolo locale non coincide.
- Fuori da `--demo` l'età dei file viene dalla data del file: dipende da come OneDrive la conserva.
- Lo stato `in_progress`/`attiva` è l'ultimo stato letto, non una prova di attività in tempo reale.
- Lettura di `~/.codex` e `~/.claude` mai provata in questo repository: solo su manas con dati veri.
- La versione precedente di questo file citava `ESPORTA_SESSIONI.bat`, che non è nel repository: l'esportazione parte da `AVVIA_DASHBOARD.bat`.
