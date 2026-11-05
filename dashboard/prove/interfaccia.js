// Prova facoltativa dell'interfaccia in --demo (richiede Node e Playwright, non sono dipendenze della dashboard).
// Uso: python dashboard.py --demo (con demo-scritture/ vuota)  poi  node prove/interfaccia.js http://127.0.0.1:8765/ demo-scritture
// Ogni controllo fallito ferma la prova con codice 1. Le schermate vanno nella cartella di questo file.
const { chromium } = require('playwright');
const fs = require('fs');
const out = __dirname, URL = process.argv[2] || 'http://127.0.0.1:8765/', SCRITTURE = process.argv[3];
let ok = 0;
const verifica = (cond, testo) => { if (!cond) throw new Error('FALLITO: ' + testo); ok++; console.log('✓', testo); };

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1360, height: 2600 } });  // alta: il trascinamento non deve far scorrere la pagina
  const p = await ctx.newPage();
  const errori = [];
  p.on('pageerror', e => errori.push(e.message));
  p.on('dialog', d => d.accept(d.type() === 'prompt' ? 'Clienti rinominati' : undefined));
  const vista = async v => { await p.click(`#schede button[data-vista="${v}"]`); await p.waitForTimeout(250); };
  const attendiCarica = () => p.waitForResponse(r => r.url().includes('/api/grafo'));
  const grafo = () => p.evaluate(async () => (await fetch('/api/grafo')).json());

  await p.goto(URL);
  await p.waitForSelector('#vista tr');

  // --- 8 viste e tempi
  const viste = await p.$$eval('#schede button', bs => bs.map(b => b.dataset.vista));
  verifica(viste.join() === 'tabella,livelli,forze,albero,proposte,cronologia,kanban,avvisi', 'ci sono le 8 viste');
  let g = await grafo();
  verifica(g.sessioni.length >= 35, `almeno 35 sessioni nei dati (${g.sessioni.length})`);
  for (const v of viste) {
    const t0 = Date.now();
    await p.click(`#schede button[data-vista="${v}"]`);
    await p.waitForFunction(v => document.querySelector('#vista').dataset.vista === v, v);
    const dt = Date.now() - t0;
    verifica(dt < 1000, `vista ${v} disegnata in ${dt} ms (< 1 s)`);
  }

  // --- filtri
  await vista('tabella');
  const tutte = await p.$$eval('#vista tbody tr', r => r.length);
  await p.fill('#testo', 'vivaio');
  const filtrate = await p.$$eval('#vista tbody tr', r => r.length);
  verifica(filtrate > 0 && filtrate < tutte, `ricerca "vivaio": ${filtrate} di ${tutte}`);
  await p.fill('#testo', '');
  await p.selectOption('#macchina', 'DEDALO');
  const soloDedalo = await p.$$eval('#vista tbody tr', r => r.map(x => x.innerText));
  verifica(soloDedalo.length > 0 && soloDedalo.every(t => t.includes('@DEDALO')), `filtro macchina DEDALO: ${soloDedalo.length} righe`);
  await p.selectOption('#macchina', '');
  await p.selectOption('#gruppo', 'g-vivaio');
  const inVivaio = await p.$$eval('#vista tbody tr', r => r.length);
  verifica(inVivaio === 3, `filtro gruppo Vivaio include il sottogruppo Schede: ${inVivaio} righe`);
  await p.selectOption('#gruppo', '');
  await p.check('#interne');
  verifica((await p.$$eval('#vista tbody tr', r => r.length)) === tutte + 1, 'il filtro guardian mostra la revisione guardian');
  await p.uncheck('#interne');

  // --- albero: crea gruppo e sottogruppo, sposta con il menu e con il trascinamento
  await vista('albero');
  await p.fill('#a-nome', 'Prova Playwright');
  await Promise.all([attendiCarica(), p.click('[data-azione="crea-gruppo"]')]);
  g = await grafo();
  const gp = g.gruppi.find(x => x.nome === 'Prova Playwright');
  verifica(gp && !gp.genitore, 'gruppo creato in cima');
  await p.fill('#a-nome', 'Sotto prova');
  await p.selectOption('#a-genitore', gp.id);
  await Promise.all([attendiCarica(), p.click('[data-azione="crea-gruppo"]')]);
  g = await grafo();
  const gs = g.gruppi.find(x => x.nome === 'Sotto prova');
  verifica(gs && gs.genitore === gp.id && gs.percorso === 'Prova Playwright › Sotto prova', 'sottogruppo creato dentro il gruppo');
  await Promise.all([attendiCarica(), p.selectOption('select[data-cambia="sposta-sessione"][data-id="demo-claude-0005"]', gs.id)]);
  g = await grafo();
  verifica(g.sessioni.find(s => s.id === 'demo-claude-0005').gruppo === gs.id, 'sessione spostata nel sottogruppo con il menu');
  await Promise.all([attendiCarica(), p.dragAndDrop('.sessione[data-trascina="s:demo-codex-0003"]', `summary[data-bersaglio="g:${gp.id}"]`)]);
  g = await grafo();
  verifica(g.sessioni.find(s => s.id === 'demo-codex-0003').gruppo === gp.id, 'sessione spostata nel gruppo trascinandola');
  await Promise.all([attendiCarica(), p.dragAndDrop(`summary[data-trascina="g:${gs.id}"]`, 'summary[data-bersaglio="g:g-interno"]')]);
  g = await grafo();
  verifica(g.gruppi.find(x => x.id === gs.id).percorso === 'Interno › Sotto prova', 'sottogruppo spostato trascinandolo in un altro gruppo');
  await Promise.all([attendiCarica(), p.click(`[data-azione="rinomina-gruppo"][data-gruppo="${gp.id}"]`)]);
  g = await grafo();
  verifica(g.gruppi.find(x => x.id === gp.id).nome === 'Clienti rinominati', 'gruppo rinominato');
  const md = await p.evaluate(async id => (await fetch('/api/esporta.md?gruppo=' + id)).text(), 'g-interno');
  verifica(md.startsWith('# Interno') && md.includes('Legenda simboli mappe'), 'esportazione Markdown del gruppo con i sottogruppi');

  // --- dettaglio: nota, etichette, collegamento manuale
  await vista('tabella');
  await p.click('[data-azione="apri"][data-id="demo-claude-0002"]');
  await p.waitForSelector('#dettaglio:not([hidden])');
  await p.fill('#d-nota', 'Nota scritta dalla prova');
  await p.fill('#d-etichette', 'prova, foto');
  await p.selectOption('#d-priorita', 'media');
  await Promise.all([attendiCarica(), p.click('[data-azione="salva-dettaglio"]')]);
  g = await grafo();
  let s2 = g.sessioni.find(s => s.id === 'demo-claude-0002');
  verifica(s2.nota === 'Nota scritta dalla prova' && s2.etichette.join() === 'prova,foto' && s2.priorita === 'media', 'nota, etichette e priorità salvate');
  await p.selectOption('#d-altra', 'demo-claude-0006');
  await p.selectOption('#d-tipo', 'continua');
  await Promise.all([attendiCarica(), p.click('[data-azione="collega"]')]);
  g = await grafo();
  verifica(g.archi.some(a => a.id === 'continua:demo-claude-0002>demo-claude-0006' && a.confidenza === 'manuale'), 'collegamento manuale aggiunto');
  await Promise.all([attendiCarica(), p.click('#dettaglio [data-azione="scollega"][data-arco="continua:demo-claude-0002>demo-claude-0006"]')]);
  g = await grafo();
  verifica(!g.archi.some(a => a.id === 'continua:demo-claude-0002>demo-claude-0006'), 'collegamento manuale tolto');
  await p.click('[data-azione="chiudi"]');

  // --- proposte: conferma, rifiuta, gruppo automatico, regola, annulla
  await vista('proposte');
  const daConfermare = g.archi.filter(a => (a.confidenza === 'probabile' || a.confidenza === 'proposta') && a.tipo !== 'stessa_cartella');
  const [uno, due] = daConfermare;
  await Promise.all([attendiCarica(), p.click(`[data-azione="decidi"][data-decisione="conferma"][data-arco="${uno.id}"]`)]);
  await Promise.all([attendiCarica(), p.click(`[data-azione="decidi"][data-decisione="rifiuta"][data-arco="${due.id}"]`)]);
  g = await grafo();
  verifica(g.archi.find(a => a.id === uno.id)?.confidenza === 'confermato', `proposta confermata (${uno.tipo})`);
  verifica(!g.archi.some(a => a.id === due.id) && g.decisioni[due.id] === 'rifiuta', `proposta rifiutata e scomparsa (${due.tipo})`);
  const auto = g.gruppi_auto.find(x => !x.decisione && x.nome.includes('fornitori'));
  await Promise.all([attendiCarica(), p.click(`[data-azione="crea-auto"][data-gruppo="${auto.id}"]`)]);
  g = await grafo();
  const nuovo = g.gruppi.find(x => x.nome === 'esempio-fornitori');
  verifica(nuovo && auto.membri.every(m => g.sessioni.find(s => s.id === m).gruppo === nuovo.id), 'gruppo automatico trasformato in gruppo manuale');
  verifica(g.gruppi_auto.find(x => x.id === auto.id).decisione === 'conferma', 'il gruppo automatico non è più proposto');
  await p.fill('#r-testo', 'catalogo');
  await p.selectOption('#r-campo', 'titolo');
  await p.selectOption('#r-gruppo', nuovo.id);
  await Promise.all([attendiCarica(), p.click('[data-azione="crea-regola"]')]);
  g = await grafo();
  verifica(g.sessioni.find(s => s.id === 'session_demo_r004').gruppo_fonte === 'regola', 'regola automatica applicata');
  const prima = (await grafo()).archi.filter(a => a.confidenza === 'proposta').length;
  await p.check('.p-sel >> nth=0'); await p.check('.p-sel >> nth=1');
  await Promise.all([attendiCarica(), p.click('[data-azione="p-blocco"][data-decisione="rifiuta"]')]);
  g = await grafo();
  verifica(Object.values(g.decisioni).filter(x => x === 'rifiuta').length >= 3, 'rifiuto in blocco di due proposte');
  await Promise.all([attendiCarica(), p.click(`[data-azione="decidi"][data-decisione="annulla_decisione"][data-arco="${due.id}"]`)]);
  g = await grafo();
  verifica(g.archi.some(a => a.id === due.id), 'decisione annullata: la proposta ricompare');

  // --- tabella: azioni in blocco
  await vista('tabella');
  await p.check('input[data-cambia="sel"][data-id="demo-manas-0009"]');
  await p.check('input[data-cambia="sel"][data-id="demo-manas-0002"]');
  await p.fill('#b-nuovo', 'Costi (blocco)');
  await Promise.all([attendiCarica(), p.click('[data-azione="b-nuovo"]')]);
  await p.selectOption('#b-tipo', 'continua');
  await Promise.all([attendiCarica(), p.click('[data-azione="b-collega"]')]);
  g = await grafo();
  const gc = g.gruppi.find(x => x.nome === 'Costi (blocco)');
  verifica(gc && gc.n === 2, 'nuovo gruppo creato dalla selezione');
  verifica(g.archi.some(a => a.id === 'continua:demo-manas-0009>demo-manas-0002'), 'collegamento in blocco in ordine di tempo');
  await p.click('[data-azione="b-svuota"]');

  // --- kanban: trascinamento e menu
  await vista('kanban');
  await Promise.all([attendiCarica(), p.dragAndDrop('.carta[data-trascina="k:demo-claude-0004"]', '.colonna[data-colonna="fatto"]')]);
  g = await grafo();
  verifica(g.sessioni.find(s => s.id === 'demo-claude-0004').colonna === 'fatto', 'carta trascinata in "fatto"');
  await Promise.all([attendiCarica(), p.selectOption('select[data-cambia="colonna"][data-id="demo-claude-0004"]', 'in attesa')]);
  g = await grafo();
  verifica(g.sessioni.find(s => s.id === 'demo-claude-0004').colonna === 'in attesa', 'carta spostata con il menu');

  // --- grafi: nodi, archi, zoom, clic sul nodo apre il dettaglio
  await vista('livelli');
  const nLiv = await p.$$eval('#tela .nodo', n => n.length), aLiv = await p.$$eval('#tela .arco', n => n.length);
  verifica(nLiv > 10 && aLiv > 10, `grafo a livelli: ${nLiv} nodi, ${aLiv} archi`);
  const tr0 = await p.getAttribute('#tela-g', 'transform');
  await p.click('[data-azione="zoom"][data-f="1.25"]');
  verifica((await p.getAttribute('#tela-g', 'transform')) !== tr0, 'lo zoom cambia la scala');
  await p.click('#tela .nodo[data-id="demo-claude-0001"]');
  verifica(await p.isVisible('#dettaglio') && (await p.textContent('#dettaglio h2')).includes('Impaginazione'), 'clic sul nodo apre il dettaglio');
  await p.click('[data-azione="chiudi"]');
  await p.uncheck('input[data-chiave="soloLegati"]');
  const nTutti = await p.$$eval('#tela .nodo', n => n.length);
  verifica(nTutti > nLiv, `senza filtro "solo legati": ${nTutti} nodi`);
  await vista('forze');
  await p.waitForTimeout(1500);
  const pos0 = await p.getAttribute('#tela .nodo[data-id="demo-claude-0001"]', 'transform');
  const box = await (await p.$('#tela .nodo[data-id="demo-claude-0001"] circle')).boundingBox();
  await p.mouse.move(box.x + 10, box.y + 10); await p.mouse.down(); await p.mouse.move(box.x + 120, box.y + 80, { steps: 8 }); await p.mouse.up();
  verifica((await p.getAttribute('#tela .nodo[data-id="demo-claude-0001"]', 'transform')) !== pos0, 'nodo del grafo a forze trascinato');
  verifica(await p.isHidden('#dettaglio'), 'il trascinamento non apre il dettaglio');
  await p.check('input[data-chiave="soloLegati"]');

  // --- cronologia e avvisi
  await vista('cronologia');
  const barre = await p.$$eval('.cronologia .barra-t', n => n.length);
  await p.selectOption('select[data-chiave="corsie"]', 'gruppo');
  const testoCorsie = await p.textContent('.cronologia svg');
  verifica(barre > 10 && testoCorsie.includes('Senza gruppo'), `cronologia: ${barre} barre, corsie per gruppo`);
  await p.selectOption('select[data-chiave="giorni"]', '1');
  verifica((await p.$$eval('.cronologia .barra-t', n => n.length)) < barre, 'periodo di 24 ore riduce le barre');
  await vista('avvisi');
  const avvisi = await p.$$eval('#vista .scheda', n => n.map(x => x.innerText));
  verifica(['Attende una risposta', 'Contesto quasi pieno', 'più macchine', 'esportazione di DEDALO', 'errore', 'nessun gruppo']
    .every(t => avvisi.some(a => a.includes(t))), `avvisi presenti (${avvisi.length})`);
  await p.click('[data-azione="vista"][data-vista="proposte"]');
  verifica(await p.isVisible('#r-testo'), 'dall\'avviso si apre la vista proposte');

  // --- persistenza dopo ricaricamento e file scritto
  await p.reload();
  await p.waitForSelector('#vista');
  await p.waitForFunction(() => document.querySelector('#vista').dataset.vista === 'proposte');
  verifica(true, 'dopo il ricaricamento resta la vista scelta');
  g = await grafo();
  verifica(g.gruppi.some(x => x.nome === 'Costi (blocco)') && g.sessioni.find(s => s.id === 'demo-claude-0002').nota === 'Nota scritta dalla prova',
    'le modifiche restano dopo il ricaricamento');
  if (SCRITTURE) {
    const reg = JSON.parse(fs.readFileSync(SCRITTURE + '/organizza-DEMO.json', 'utf8'));
    verifica(reg.macchina === 'DEMO' && reg.operazioni.length > 20, `registro demo-scritture/organizza-DEMO.json con ${reg.operazioni.length} operazioni`);
  }

  // --- tema e telefono
  await p.click('#tema'); await p.click('#tema');
  verifica((await p.evaluate(() => document.documentElement.dataset.theme)) === 'dark', 'tema scuro scelto a mano');
  await p.click('#tema');
  await p.screenshot({ path: out + '/prova-desktop.png' });
  const tel = await b.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'dark', isMobile: true, hasTouch: true });
  const q = await tel.newPage();
  q.on('pageerror', e => errori.push('telefono: ' + e.message));
  await q.goto(URL);
  await q.waitForSelector('#vista tbody tr');
  for (const v of viste) {
    await q.click(`#schede button[data-vista="${v}"]`);
    await q.waitForTimeout(v === 'forze' ? 800 : 200);
    const larg = await q.evaluate(() => document.documentElement.scrollWidth);
    verifica(larg <= 390, `telefono, vista ${v}: nessuno scorrimento orizzontale (${larg} px)`);
    if (['tabella', 'albero', 'livelli', 'kanban'].includes(v)) await q.screenshot({ path: `${out}/telefono-${v}.png` });
  }
  verifica((await q.evaluate(() => getComputedStyle(document.body).backgroundColor)) === 'rgb(26, 26, 25)', 'telefono in tema scuro');
  await q.click(`#schede button[data-vista="albero"]`);
  await q.click('[data-azione="apri"][data-id="demo-claude-0001"]');
  const det = await (await q.$('#dettaglio')).boundingBox();
  verifica(det.width <= 390, 'il dettaglio sta nella larghezza del telefono');

  verifica(errori.length === 0, 'nessun errore JavaScript ' + JSON.stringify(errori));
  console.log(`\n${ok} controlli superati`);
  await b.close();
})().catch(e => { console.error(e.message); process.exit(1); });
