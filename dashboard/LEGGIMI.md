# Dashboard sessioni (prototipo, 2026-10-20)

Avvio: doppio clic su `AVVIA_DASHBOARD.bat`, oppure `python dashboard.py`, poi http://127.0.0.1:8765 (solo locale, si aggiorna ogni 30 s).
Legge in sola lettura; non legge credenziali (`~/.codex/auth.json` escluso). Scrive solo con `--esporta`.

| Fonte | Da dove | Aggiornamento |
|---|---|---|
| Codex della macchina | `~/.codex/state_5.sqlite` (threads, remote_control_enrollments) + coda dei rollout | automatico |
| Claude Code della macchina | `~/.claude/projects/*/*.jsonl` | automatico |
| Claude remoto (cloud, Remote Control) | `claude_remoto.json` (accanto allo script o in `dati\`), scritto da una sessione Claude con `list_sessions` | istantanea: va rigenerata |
| Altre macchine | `dati\<MACCHINA>.json`, scritti da `ESPORTA_SESSIONI.bat` (`--esporta --ogni 60`) | ogni 60 s finché l'esportazione gira |
| Cowork, ChatGPT | — | non raggiungibili, controllo manuale |

## Più macchine (manas + dedalo)
Questa cartella (`C:\Onedrive\_ELE\AI_OFFICINA\dashboard`) è sincronizzata su manas e dedalo.
Su ciascuna macchina: doppio clic su `AVVIA_DASHBOARD.bat`. Avvia l'esportazione (finestra ridotta, scrive
`dati\<MACCHINA>.json` ogni 60 s) e la dashboard, che mostra le sessioni locali + quelle delle altre macchine.
Serve Python (python.org, "Add python.exe to PATH"). Originale di sviluppo: `C:\OFFICINA_AI\dashboard` su manas.
L'esportazione contiene solo strumento, tipo, titolo, modello, stato, orario e id: niente messaggi né cartelle.
Se un'esportazione è più vecchia di 5 minuti viene segnalata e gli stati "attiva" diventano "sconosciuto".

## Limiti noti
- I formati dei file Codex e Claude non sono documentati: possono cambiare a ogni aggiornamento.
- "attiva" = attività negli ultimi 3 minuti; per Codex "in lavoro" se l'ultimo turno è iniziato e non concluso.
- La stessa sessione può comparire due volte (locale e remota) quando il titolo locale non coincide.
- Una seconda dashboard sulla stessa porta si rifiuta di partire; porta diversa con la variabile `PORT`.
