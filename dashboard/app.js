"use strict";
// Dashboard sessioni: 8 viste, pannello dettagli, organizzazione. Nessuna libreria esterna.

const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ms = iso => (iso ? Date.parse(iso) : NaN);
const quando = iso => {
  if (!iso) return "—";
  const m = (Date.now() - ms(iso)) / 60000;
  if (m < 1) return "ora";
  if (m < 60) return Math.round(m) + " min fa";
  if (m < 1440) return Math.round(m / 60) + " h fa";
  return new Date(iso).toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
};
const corto = (t, n) => (t = String(t ?? ""), t.length > n ? t.slice(0, n - 1) + "…" : t);
const classeStato = st => "s-" + String(st || "sconosciuto").replace(/[ ?]+/g, "-").replace(/-$/, "");
const chip = s => `<span class="chip ${classeStato(s.stato)}">${esc(s.stato)}</span>`;
const nuovoId = p => p + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const colore = (id, a = 1) => {
  let h = 0;
  for (const c of String(id || "")) h = (h * 31 + c.charCodeAt(0)) % 360;
  return id ? `hsl(${h} 55% 50% / ${a})` : `hsl(0 0% 50% / ${a})`;
};
const NS = "http://www.w3.org/2000/svg";

const VISTE = [["tabella", "Tabella"], ["livelli", "Grafo a livelli"], ["forze", "Grafo a forze"], ["albero", "Albero"],
  ["proposte", "Proposte"], ["cronologia", "Cronologia"], ["kanban", "Kanban"], ["avvisi", "Avvisi"]];
const PASSIVI = ["ferma", "completata", "archiviata", "sconosciuto", "offline"];
const TIPI = { padre: "genitore → figlio", cita: "cita", stessa_pr: "stessa PR", stessa_cartella: "stessa cartella",
  simile: "titoli simili", dipende_da: "prerequisito di", continua: "continua in", duplicato: "duplicato di", correlato: "correlata a" };
const TIPI_MANUALI = ["dipende_da", "continua", "duplicato", "correlato"];
const CONF = { certo: "certo", probabile: "probabile", proposta: "da confermare", confermato: "confermato", manuale: "manuale" };

// --- stato dell'interfaccia (ricordato nel browser, se possibile) --------------------------------------------------
const PREDEFINITI = { vista: "tabella", testo: "", macchina: "", gruppo: "", interne: false, ferme: true, nascoste: false,
  proposte: true, deboli: false, soloLegati: true, corsie: "macchina", giorni: 7, tema: "", chiusi: [] };
let U = { ...PREDEFINITI };
try { U = { ...PREDEFINITI, ...JSON.parse(localStorage.getItem("dashboard-ui") || "{}") }; } catch (e) { /* senza memoria */ }
const salvaUI = () => { try { localStorage.setItem("dashboard-ui", JSON.stringify(U)); } catch (e) { /* ignora */ } };

let D = null;                 // dati da /api/grafo
let PER = {};                 // id → sessione
let GR = {};                  // id → gruppo
let selezionati = new Set();
let dettaglio = null;
let trascina = false;
const tele = {};              // stato di zoom e spostamento per vista
const posForze = {};          // posizioni del grafo a forze
let animazione = null;

// --- dati ---------------------------------------------------------------------------------------------------------
async function carica() {
  try {
    const r = await fetch("/api/grafo", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    D = await r.json();
  } catch (e) {
    $("#gen").textContent = "Errore nel caricamento: " + e.message;
    return;
  }
  PER = Object.fromEntries(D.sessioni.map(s => [s.id, s]));
  GR = Object.fromEntries(D.gruppi.map(g => [g.id, g]));
  for (const id of [...selezionati]) if (!PER[id]) selezionati.delete(id);
  disegna();
}

async function invia(operazioni, testo) {
  try {
    const r = await fetch("/api/organizza", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operazioni }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.errore || "HTTP " + r.status);
    if (testo) avvisa(testo);
  } catch (e) {
    avvisa("Non salvato: " + e.message);
  }
  await carica();
}

let timerMsg = null;
function avvisa(t) {
  const m = $("#messaggio");
  m.textContent = t;
  m.hidden = false;
  clearTimeout(timerMsg);
  timerMsg = setTimeout(() => (m.hidden = true), 3500);
}

function discendenti(gid) {
  const out = new Set([gid]);
  let cambiato = true;
  while (cambiato) {
    cambiato = false;
    for (const g of D.gruppi) if (out.has(g.genitore) && !out.has(g.id)) { out.add(g.id); cambiato = true; }
  }
  return out;
}

function visibili() {
  const q = U.testo.trim().toLowerCase();
  const nelGruppo = U.gruppo === "_nessuno" ? null : (U.gruppo && GR[U.gruppo] ? discendenti(U.gruppo) : null);
  return D.sessioni.filter(s => (U.interne || !s.interna) && (U.ferme || !PASSIVI.includes(s.stato))
    && (U.nascoste || !s.nascosta) && (!U.macchina || (s.macchina || "remoto") === U.macchina)
    && (U.gruppo !== "_nessuno" || !s.gruppo) && (!nelGruppo || nelGruppo.has(s.gruppo))
    && (!q || [s.titolo, s.progetto, s.sezione_codex, s.progetto_codex, s.id, s.nota, s.prossima_azione, s.gruppo_percorso, s.strumento, ...(s.etichette || [])]
      .some(v => String(v || "").toLowerCase().includes(q))));
}

function archiTra(ids) {
  return D.archi.filter(a => ids.has(a.da) && ids.has(a.a) && (U.deboli || a.tipo !== "stessa_cartella")
    && (U.proposte || a.confidenza !== "proposta"));
}

const daConfermare = a => (a.confidenza === "probabile" || a.confidenza === "proposta") && a.tipo !== "stessa_cartella";

// --- disegno generale ---------------------------------------------------------------------------------------------
function disegna() {
  if (!D) return;
  if (animazione) { cancelAnimationFrame(animazione); animazione = null; }
  $("#demo").hidden = !D.demo;
  const proposteN = D.archi.filter(daConfermare).length + D.gruppi_auto.filter(g => !g.decisione).length;
  const avvisiN = D.avvisi.filter(a => a.livello === "attenzione").length;
  $("#schede").innerHTML = VISTE.map(([k, n]) => `<button data-azione="vista" data-vista="${k}" aria-pressed="${U.vista === k}">${n}`
    + (k === "proposte" && proposteN ? ` <span class="conta">${proposteN}</span>` : "")
    + (k === "avvisi" && avvisiN ? ` <span class="conta">⚠ ${avvisiN}</span>` : "") + "</button>").join("");
  const macchine = [...new Set(D.sessioni.map(s => s.macchina || "remoto"))].sort();
  $("#macchina").innerHTML = `<option value="">tutte le macchine</option>` + macchine.map(m =>
    `<option value="${esc(m)}"${m === U.macchina ? " selected" : ""}>${m === "remoto" ? "remoto (cloud)" : "@" + esc(m)}</option>`).join("");
  $("#gruppo").innerHTML = `<option value="">tutti i gruppi</option><option value="_nessuno"${U.gruppo === "_nessuno" ? " selected" : ""}>senza gruppo</option>`
    + D.gruppi.map(g => `<option value="${esc(g.id)}"${g.id === U.gruppo ? " selected" : ""}>${esc(g.percorso)} (${g.n})</option>`).join("");
  $("#testo").value = U.testo;
  for (const k of ["interne", "ferme", "nascoste"]) $("#" + k).checked = U[k];
  const vis = visibili();
  $("#gen").textContent = `${D.demo ? "Modalità dimostrativa · " : ""}Aggiornato ${new Date(D.generato).toLocaleTimeString("it-IT")} · `
    + `${vis.length} di ${D.sessioni.length} sessioni · si aggiorna ogni 30 s`;
  const el = $("#vista");
  el.dataset.vista = U.vista;
  ({ tabella: vistaTabella, livelli: vistaLivelli, forze: vistaForze, albero: vistaAlbero, proposte: vistaProposte,
    cronologia: vistaCronologia, kanban: vistaKanban, avvisi: vistaAvvisi }[U.vista] || vistaTabella)(el, vis);
  $("#fonti").innerHTML = Object.entries(D.fonti).map(([n, f]) => `<div class="fonte"><b>${esc(n)}</b> · ${f.n}<br>${esc(f.nota)}</div>`).join("");
  $("#manuali").innerHTML = D.manuali.map(m => `<div><b>${esc(m.strumento)}</b>: ${esc(m.nota)}</div>`).join("")
    + `<div>Le modifiche di organizzazione vengono scritte in <code>${esc(D.organizza.scrive_in)}</code></div>`;
  disegnaDettaglio();
}

const opzioniGruppi = (scelto, vuoto = "— nessun gruppo", valoreVuoto = "") => `<option value="${valoreVuoto}">${vuoto}</option>`
  + D.gruppi.map(g => `<option value="${esc(g.id)}"${g.id === scelto ? " selected" : ""}>${esc(g.percorso)}</option>`).join("");
const macchinaTag = s => (s.macchina ? ` <span class="cart">@${esc(s.macchina)}</span>` : ` <span class="cart">cloud</span>`)
  + (s.anche_su && s.anche_su.length ? ` <span class="cart">(anche su ${esc(s.anche_su.join(", "))})</span>` : "");
const gruppoTag = s => s.gruppo ? `<span class="gruppo-tag" style="border-left:3px solid ${colore(s.gruppo)}">${esc(s.gruppo_percorso)}${s.gruppo_fonte === "regola" ? " · regola" : ""}</span>` : "";
const etichetteTag = s => (s.etichette || []).map(e => `<span class="etichetta">${esc(e)}</span>`).join("")
  + (s.priorita ? `<span class="etichetta prio-${esc(s.priorita)}">priorità ${esc(s.priorita)}</span>` : "");

// --- 1. tabella ---------------------------------------------------------------------------------------------------
function vistaTabella(el, vis) {
  const blocco = selezionati.size ? `<div class="blocco" id="blocco"><b>${selezionati.size} selezionate</b>
    <select id="b-gruppo" aria-label="Gruppo di destinazione">${opzioniGruppi("", "— scegli gruppo")}</select>
    <button data-azione="b-sposta">Sposta nel gruppo</button><button data-azione="b-togli">Togli dal gruppo</button>
    <input type="text" id="b-nuovo" placeholder="nome nuovo gruppo" aria-label="Nome nuovo gruppo"><button data-azione="b-nuovo">Nuovo gruppo con queste</button>
    <select id="b-tipo" aria-label="Tipo di collegamento">${TIPI_MANUALI.map(t => `<option value="${t}">${TIPI[t]}</option>`).join("")}</select>
    <button data-azione="b-collega">Collega in ordine di tempo</button>
    <input type="text" id="b-etichetta" placeholder="etichetta" aria-label="Etichetta"><button data-azione="b-etichetta">Aggiungi etichetta</button>
    <button data-azione="b-nascondi">Nascondi</button><button data-azione="b-svuota">Deseleziona</button></div>` : "";
  el.innerHTML = blocco + `<table class="tab-sessioni"><thead><tr><th><input type="checkbox" id="sel-tutte" aria-label="Seleziona tutte"></th>
    <th>Stato</th><th>Strumento</th><th>Sessione</th><th>Ultima attività</th><th>Ultimo messaggio / prossima azione</th></tr></thead><tbody>`
    + (vis.map(s => `<tr data-id="${esc(s.id)}"${selezionati.has(s.id) ? ' class="selezionata"' : ""}>
      <td><input type="checkbox" data-cambia="sel" data-id="${esc(s.id)}"${selezionati.has(s.id) ? " checked" : ""} aria-label="Seleziona"></td>
      <td>${chip(s)}</td>
      <td><b>${esc(s.strumento)}</b>${macchinaTag(s)}<div class="msg">${esc(s.tipo)}${s.modello ? " · " + esc(s.modello) : ""}</div></td>
      <td><button class="titolo-link" data-azione="apri" data-id="${esc(s.id)}">${esc(s.titolo || s.id)}</button>
        <div class="cart">${esc(s.cartella || s.progetto || "")}</div>${gruppoTag(s)} ${etichetteTag(s)}</td>
      <td>${quando(s.ultima_attivita)}</td>
      <td class="msg">${s.prossima_azione ? "<b>→ " + esc(s.prossima_azione) + "</b><br>" : ""}${esc(s.ultimo_messaggio)}</td></tr>`).join("")
      || `<tr><td colspan="6">Nessuna sessione con questi filtri.</td></tr>`) + "</tbody></table>";
  $("#sel-tutte").checked = vis.length > 0 && vis.every(s => selezionati.has(s.id));
}

// --- zoom e spostamento per i grafi ---------------------------------------------------------------------------------
function tela(svg, g, chiave) {
  const st = tele[chiave] || (tele[chiave] = { x: 10, y: 10, k: 1, iniziale: true });
  const applica = () => g.setAttribute("transform", `translate(${st.x},${st.y}) scale(${st.k})`);
  applica();
  svg.addEventListener("wheel", e => {
    e.preventDefault();
    const r = svg.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    const k = Math.min(3, Math.max(0.15, st.k * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
    st.x = px - (px - st.x) * k / st.k; st.y = py - (py - st.y) * k / st.k; st.k = k; applica();
  }, { passive: false });
  let pan = null;
  svg.addEventListener("pointerdown", e => {
    if (e.target.closest(".nodo")) return;
    pan = { x: e.clientX - st.x, y: e.clientY - st.y };
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", e => { if (pan) { st.x = e.clientX - pan.x; st.y = e.clientY - pan.y; applica(); } });
  svg.addEventListener("pointerup", () => (pan = null));
  return {
    st, applica,
    zoom(f) { const r = svg.getBoundingClientRect(), cx = r.width / 2, cy = r.height / 2, k = Math.min(3, Math.max(0.15, st.k * f));
      st.x = cx - (cx - st.x) * k / st.k; st.y = cy - (cy - st.y) * k / st.k; st.k = k; applica(); },
    adatta(x0, y0, w, h) { const r = svg.getBoundingClientRect(); if (!r.width) return;
      st.k = Math.min(1.4, Math.max(0.15, Math.min((r.width - 20) / Math.max(w, 1), (r.height - 20) / Math.max(h, 1))));
      st.x = 10 - x0 * st.k + Math.max(0, (r.width - 20 - w * st.k) / 2); st.y = 10 - y0 * st.k; applica(); },
  };
}

const controlliGrafo = (extra = "") => `<div class="controlli">
  <button data-azione="zoom" data-f="1.25" aria-label="Ingrandisci">＋</button><button data-azione="zoom" data-f="0.8" aria-label="Riduci">－</button>
  <button data-azione="adatta">Adatta</button>
  <label><input type="checkbox" data-cambia="ui" data-chiave="soloLegati"${U.soloLegati ? " checked" : ""}> solo sessioni con legami</label>
  <label><input type="checkbox" data-cambia="ui" data-chiave="proposte"${U.proposte ? " checked" : ""}> proposte</label>
  <label><input type="checkbox" data-cambia="ui" data-chiave="deboli"${U.deboli ? " checked" : ""}> stessa cartella</label>${extra}</div>`;
const legenda = `<div class="legenda"><span><i style="border-color:var(--accent);border-top-width:3px"></i>genitore → figlio</span>
  <span><i style="border-color:var(--work);border-top-style:dotted"></i>cita / stessa PR</span>
  <span><i style="border-color:var(--muted);border-top-style:dashed"></i>proposta (titoli simili)</span>
  <span><i style="border-color:var(--ok);border-top-width:3px"></i>manuale o confermato</span>
  <span><i style="border-color:var(--line)"></i>stessa cartella</span><span>Rotella o ＋/－ per lo zoom, trascina lo sfondo per spostare.</span></div>`;
let telaAttiva = null;

function nodiEArchi(vis) {
  const ids = new Set(vis.map(s => s.id));
  const archi = archiTra(ids);
  let nodi = vis;
  if (U.soloLegati) {
    const con = new Set(archi.flatMap(a => [a.da, a.a]));
    nodi = vis.filter(s => con.has(s.id));
  }
  return { nodi, archi, esclusi: vis.length - nodi.length };
}

function svgNodo(s, x, y, W, H) {
  return `<g class="nodo${dettaglio === s.id ? " attivo" : ""}" data-azione="apri" data-id="${esc(s.id)}" transform="translate(${x},${y})">
    <title>${esc(s.titolo)} · ${esc(s.stato)}</title><rect class="n-bg" width="${W}" height="${H}" rx="7"/>
    <rect class="n-stato ${classeStato(s.stato)}" width="6" height="${H}" rx="3"/>
    <text x="12" y="18">${esc(corto(s.titolo || s.id, 30))}</text>
    <text class="n-sub" x="12" y="35">${esc(corto(`${s.strumento}${s.macchina ? " @" + s.macchina : ""} · ${quando(s.ultima_attivita)}`, 36))}</text></g>`;
}

// livelli = percorso più lungo su un grafo senza cicli: ordinamento topologico (prima le sessioni più vecchie);
// quando restano solo cicli, si ignorano gli archi che entrano nella sessione più vecchia rimasta
function livelli(nodi, archi) {
  const entrata = {}, uscita = {}, L = {};
  for (const s of nodi) { entrata[s.id] = new Set(); uscita[s.id] = []; L[s.id] = 0; }
  for (const a of archi) if (a.da !== a.a) { entrata[a.a].add(a.da); uscita[a.da].push(a.a); }
  const restanti = new Set(nodi.map(s => s.id));
  const perTempo = [...nodi].sort((x, y) => String(x.ultima_attivita).localeCompare(String(y.ultima_attivita))).map(s => s.id);
  while (restanti.size) {
    let id = perTempo.find(x => restanti.has(x) && [...entrata[x]].every(p => !restanti.has(p)));
    if (id === undefined) id = perTempo.find(x => restanti.has(x));   // ciclo: si rompe qui
    restanti.delete(id);
    for (const f of uscita[id]) if (restanti.has(f)) L[f] = Math.max(L[f], L[id] + 1);
  }
  return L;
}

// --- 2. grafo a livelli ------------------------------------------------------------------------------------------------
function vistaLivelli(el, vis) {
  const { nodi, archi, esclusi } = nodiEArchi(vis);
  const nota = esclusi ? ` <span class="sub">${esclusi} sessioni senza legami nascoste</span>` : "";
  if (!nodi.length) { el.innerHTML = controlliGrafo(nota) + `<div class="vuoto">Nessun legame tra le sessioni visibili.</div>`; return; }
  const L = livelli(nodi, archi);
  const banda = id => PER[id].gruppo || "";
  const bande = new Map();
  for (const s of nodi) { const k = banda(s.id); if (!bande.has(k)) bande.set(k, []); bande.get(k).push(s); }
  const chiavi = [...bande.keys()].sort((a, b) => (a === "") - (b === "") || (GR[a]?.percorso || "").localeCompare(GR[b]?.percorso || ""));
  const W = 220, H = 46, CX = 270, GY = 12, PAD = 28;
  const pos = {}, scatole = [];
  let y0 = 0;
  const ordine = {};
  for (const k of chiavi) {
    const perL = [];
    for (const s of bande.get(k)) (perL[L[s.id]] ||= []).push(s);
    perL.forEach(c => c && c.sort((a, b) => String(a.ultima_attivita).localeCompare(String(b.ultima_attivita))));
    for (let passo = 0; passo < 2; passo++) {   // ordinamento baricentrico
      perL.forEach(c => c && c.forEach((s, i) => (ordine[s.id] = i)));
      perL.forEach((c, li) => {
        if (!c || !li) return;
        const bc = s => { const p = archi.filter(a => a.a === s.id && banda(a.da) === k && ordine[a.da] !== undefined).map(a => ordine[a.da]);
          return p.length ? p.reduce((x, y) => x + y, 0) / p.length : ordine[s.id]; };
        c.sort((a, b) => bc(a) - bc(b));
      });
    }
    const righe = Math.max(...Array.from(perL, c => (c ? c.length : 0)));
    perL.forEach((c, li) => c && c.forEach((s, i) => (pos[s.id] = { x: 16 + li * CX, y: y0 + PAD + i * (H + GY) })));
    const h = PAD + righe * (H + GY) + 4;
    scatole.push({ k, y: y0, h });
    y0 += h + 14;
  }
  const maxL = Math.max(...nodi.map(s => L[s.id]));
  const larg = 32 + maxL * CX + W;
  const linee = archi.map(a => {
    const p = pos[a.da], q = pos[a.a];
    let d;
    if (q.x > p.x) d = `M${p.x + W},${p.y + H / 2} C${p.x + W + 50},${p.y + H / 2} ${q.x - 50},${q.y + H / 2} ${q.x},${q.y + H / 2}`;
    else d = `M${p.x + W / 2},${p.y + H} C${p.x + W / 2 + 60},${p.y + H + 50} ${q.x + W / 2 + 60},${q.y - 50} ${q.x + W / 2},${q.y}`;
    return `<path class="arco t-${a.tipo} c-${a.confidenza}" d="${d}" marker-end="url(#freccia)"><title>${esc(TIPI[a.tipo] || a.tipo)} · ${esc(CONF[a.confidenza])} · ${esc(a.prova || "")}</title></path>`;
  }).join("");
  const sfondi = scatole.map(b => `<rect x="4" y="${b.y}" width="${larg}" height="${b.h}" rx="10" fill="${colore(b.k, 0.09)}" stroke="${colore(b.k, 0.35)}"/>
    <text class="banda-titolo" x="14" y="${b.y + 18}">${esc(b.k ? GR[b.k]?.percorso : "Senza gruppo")}</text>`).join("");
  el.innerHTML = controlliGrafo(nota) + `<svg class="tela" id="tela" aria-label="Grafo a livelli"><defs><marker id="freccia" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor" opacity=".6"/></marker></defs>
    <g id="tela-g">${sfondi}${linee}${nodi.map(s => svgNodo(s, pos[s.id].x, pos[s.id].y, W, H)).join("")}</g></svg>` + legenda;
  const svg = $("#tela");
  telaAttiva = tela(svg, $("#tela-g"), "livelli");
  telaAttiva.limiti = [0, 0, larg + 8, y0];
  if (telaAttiva.st.iniziale) { telaAttiva.adatta(0, 0, larg + 8, y0); telaAttiva.st.iniziale = false; }
}

// --- 3. grafo a forze ------------------------------------------------------------------------------------------------
function vistaForze(el, vis) {
  const { nodi, archi, esclusi } = nodiEArchi(vis);
  const nota = esclusi ? ` <span class="sub">${esclusi} sessioni senza legami nascoste</span>` : "";
  const extra = ` <button data-azione="forze-pausa">${tele.forzePausa ? "Riprendi" : "Pausa"}</button> <button data-azione="forze-rimescola">Rimescola</button>` + nota;
  if (!nodi.length) { el.innerHTML = controlliGrafo(extra) + `<div class="vuoto">Nessun legame tra le sessioni visibili.</div>`; return; }
  const gruppi = [...new Set(nodi.map(s => s.gruppo || ""))];
  nodi.forEach((s, i) => {
    if (!posForze[s.id]) {
      const gi = gruppi.indexOf(s.gruppo || ""), ang = (gi / gruppi.length) * Math.PI * 2;
      posForze[s.id] = { x: Math.cos(ang) * 220 + (i % 7) * 9, y: Math.sin(ang) * 220 + (i % 5) * 9, vx: 0, vy: 0 };
    }
  });
  el.innerHTML = controlliGrafo(extra) + `<svg class="tela" id="tela" aria-label="Grafo a forze"><g id="tela-g">
    ${archi.map((a, i) => `<line class="arco t-${a.tipo} c-${a.confidenza}" data-i="${i}"><title>${esc(TIPI[a.tipo] || a.tipo)} · ${esc(a.prova || "")}</title></line>`).join("")}
    ${nodi.map(s => `<g class="nodo${dettaglio === s.id ? " attivo" : ""}" data-azione="apri" data-id="${esc(s.id)}"><title>${esc(s.titolo)} · ${esc(s.gruppo_percorso || "senza gruppo")}</title>
      <circle r="10" class="f-nodo ${classeStato(s.stato)}" stroke="${colore(s.gruppo, 0.9)}"/><text x="14" y="4">${esc(corto(s.titolo, 26))}</text></g>`).join("")}
    </g></svg><div class="legenda">${gruppi.map(g => `<span><i style="border-color:${colore(g)};border-top-width:4px"></i>${esc(g ? GR[g]?.percorso : "senza gruppo")}</span>`).join("")}
    <span>Riempimento = stato, bordo = gruppo. Trascina i nodi per sistemarli.</span></div>`;
  const svg = $("#tela");
  telaAttiva = tela(svg, $("#tela-g"), "forze");
  if (telaAttiva.st.iniziale) { const r = svg.getBoundingClientRect(); telaAttiva.st.x = r.width / 2; telaAttiva.st.y = r.height / 2; telaAttiva.st.k = 1; telaAttiva.applica(); telaAttiva.st.iniziale = false; }
  const linee = [...svg.querySelectorAll("line")], gNodi = [...svg.querySelectorAll(".nodo")];
  const P = nodi.map(s => posForze[s.id]);
  const idx = Object.fromEntries(nodi.map((s, i) => [s.id, i]));
  let alfa = tele.forzeAlfa ?? 1;
  function passo() {
    const n = P.length;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const dx = P[j].x - P[i].x, dy = P[j].y - P[i].y, d2 = Math.max(dx * dx + dy * dy, 30);
      const f = 5200 * alfa / d2, fx = dx * f / Math.sqrt(d2), fy = dy * f / Math.sqrt(d2);
      P[i].vx -= fx; P[i].vy -= fy; P[j].vx += fx; P[j].vy += fy;
    }
    for (const a of archi) {
      const p = P[idx[a.da]], q = P[idx[a.a]], dx = q.x - p.x, dy = q.y - p.y, d = Math.max(Math.hypot(dx, dy), 1);
      const f = (d - 120) * 0.05 * alfa, fx = dx / d * f, fy = dy / d * f;
      p.vx += fx; p.vy += fy; q.vx -= fx; q.vy -= fy;
    }
    const centri = {};
    nodi.forEach((s, i) => { const c = centri[s.gruppo || ""] ||= { x: 0, y: 0, n: 0 }; c.x += P[i].x; c.y += P[i].y; c.n++; });
    nodi.forEach((s, i) => {
      const c = centri[s.gruppo || ""], p = P[i];
      if (s.gruppo) { p.vx += (c.x / c.n - p.x) * 0.03 * alfa; p.vy += (c.y / c.n - p.y) * 0.03 * alfa; }
      p.vx -= p.x * 0.012 * alfa; p.vy -= p.y * 0.012 * alfa;
      if (!p.fisso) { p.x += p.vx; p.y += p.vy; }
      p.vx *= 0.55; p.vy *= 0.55;
    });
  }
  function aggiorna() {
    archi.forEach((a, i) => { const p = P[idx[a.da]], q = P[idx[a.a]], l = linee[i];
      l.setAttribute("x1", p.x); l.setAttribute("y1", p.y); l.setAttribute("x2", q.x); l.setAttribute("y2", q.y); });
    gNodi.forEach((g, i) => g.setAttribute("transform", `translate(${P[i].x},${P[i].y})`));
  }
  function ciclo() {
    passo(); aggiorna();
    alfa *= 0.985; tele.forzeAlfa = alfa;
    animazione = alfa > 0.02 ? requestAnimationFrame(ciclo) : null;
  }
  aggiorna();
  if (alfa > 0.02 && !tele.forzePausa) animazione = requestAnimationFrame(ciclo);
  tele.riscalda = () => { alfa = Math.max(alfa, 0.5); tele.forzePausa = false; if (!animazione) animazione = requestAnimationFrame(ciclo); };
  tele.ferma = () => { tele.forzePausa = true; if (animazione) cancelAnimationFrame(animazione); animazione = null; };
  // trascinamento dei nodi (un clic senza movimento apre il dettaglio)
  let preso = null;
  svg.addEventListener("pointerdown", e => {
    const g = e.target.closest(".nodo");
    if (!g) return;
    const i = idx[g.dataset.id];
    preso = { i, x0: e.clientX, y0: e.clientY, mosso: false };
    trascina = true;
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", e => {
    if (!preso) return;
    const st = telaAttiva.st, p = P[preso.i];
    if (Math.hypot(e.clientX - preso.x0, e.clientY - preso.y0) > 4) preso.mosso = true;
    if (!preso.mosso) return;
    const r = svg.getBoundingClientRect();
    p.x = (e.clientX - r.left - st.x) / st.k; p.y = (e.clientY - r.top - st.y) / st.k; p.fisso = true;
    aggiorna();
  });
  svg.addEventListener("pointerup", e => {
    if (preso && preso.mosso) { svg.dataset.trascinato = "1"; setTimeout(() => delete svg.dataset.trascinato, 0); tele.riscalda(); }
    preso = null; trascina = false;
  });
}

// --- 4. albero annidato -------------------------------------------------------------------------------------------------
function vistaAlbero(el, vis) {
  const ids = new Set(vis.map(s => s.id));
  const figliDi = {};
  for (const a of D.archi) {
    if (!ids.has(a.da) || !ids.has(a.a)) continue;
    if (a.tipo === "padre" || ((a.confidenza === "manuale" || a.confidenza === "confermato") && (a.tipo === "continua" || a.tipo === "dipende_da")))
      (figliDi[a.da] ||= []).push(a.a);
  }
  const bucket = s => s.gruppo || "";
  const annidata = new Set();
  for (const [p, figli] of Object.entries(figliDi)) for (const f of figli) if (PER[p] && bucket(PER[p]) === bucket(PER[f]) && f !== p) annidata.add(f);
  const sessioneLi = (s, visti) => {
    visti = new Set(visti).add(s.id);
    const figli = (figliDi[s.id] || []).filter(f => !visti.has(f) && bucket(PER[f]) === bucket(s));
    return `<li><div class="sessione" draggable="true" data-trascina="s:${esc(s.id)}">${chip(s)}
      <button class="titolo-link" data-azione="apri" data-id="${esc(s.id)}">${esc(s.titolo || s.id)}</button>${macchinaTag(s)}
      ${s.gruppo_fonte === "regola" ? '<span class="etichetta">regola</span>' : ""}${etichetteTag(s)}
      <select data-cambia="sposta-sessione" data-id="${esc(s.id)}" aria-label="Sposta in">${opzioniGruppi(s.gruppo_fonte === "manuale" ? s.gruppo : "", "Sposta in…")}<option value="_togli">— togli dal gruppo</option></select></div>
      ${figli.length ? `<ul>${figli.map(f => sessioneLi(PER[f], visti)).join("")}</ul>` : ""}</li>`;
  };
  const radici = b => vis.filter(s => bucket(s) === b && !annidata.has(s.id));
  const gruppoLi = g => {
    const sotto = D.gruppi.filter(x => x.genitore === g.id);
    const chiuso = U.chiusi.includes(g.id);
    return `<li><details${chiuso ? "" : " open"} data-gruppo="${esc(g.id)}"><summary class="g-testa" data-bersaglio="g:${esc(g.id)}" draggable="true" data-trascina="g:${esc(g.id)}">
      <b style="border-left:4px solid ${colore(g.id)};padding-left:6px">${esc(g.nome)}</b><span class="sub">${g.n} sessioni</span>
      <a href="/api/esporta.md?gruppo=${encodeURIComponent(g.id)}" target="_blank" rel="noopener">Markdown</a>
      <button data-azione="rinomina-gruppo" data-gruppo="${esc(g.id)}">Rinomina</button>
      <button data-azione="elimina-gruppo" data-gruppo="${esc(g.id)}">Elimina</button>
      <select data-cambia="sposta-gruppo" data-gruppo="${esc(g.id)}" aria-label="Sposta il gruppo dentro">
        <option value="">Sposta dentro…</option><option value="_radice">— in cima</option>
        ${D.gruppi.filter(x => !discendenti(g.id).has(x.id)).map(x => `<option value="${esc(x.id)}">${esc(x.percorso)}</option>`).join("")}</select></summary>
      <ul>${sotto.map(gruppoLi).join("")}${radici(g.id).map(s => sessioneLi(s, [])).join("")}</ul></details></li>`;
  };
  const senza = radici("");
  el.innerHTML = `<div class="form-riga"><input type="text" id="a-nome" placeholder="Nome del nuovo gruppo" aria-label="Nome del nuovo gruppo">
      <select id="a-genitore" aria-label="Dentro il gruppo">${opzioniGruppi("", "— in cima")}</select><button class="primario" data-azione="crea-gruppo">Crea gruppo</button>
      <span class="sub">Trascina sessioni e gruppi sui titoli dei gruppi, oppure usa i menu “Sposta”.</span></div>
    <div class="albero"><ul>${D.gruppi.filter(g => !g.genitore).map(gruppoLi).join("")}
    <li><details open><summary class="g-testa" data-bersaglio="g:"><b>Senza gruppo</b><span class="sub">${senza.length} sessioni</span>
      <a href="/api/esporta.md" target="_blank" rel="noopener">Markdown</a></summary><ul>${senza.map(s => sessioneLi(s, [])).join("")}</ul></details></li></ul></div>`;
}

// --- 5. proposte ----------------------------------------------------------------------------------------------------------
function vistaProposte(el) {
  const titolo = id => esc(PER[id]?.titolo || id);
  const auto = D.gruppi_auto.filter(g => !g.decisione);
  const archi = D.archi.filter(daConfermare);
  const prese = Object.entries(D.decisioni || {});
  el.innerHTML = `<h2>Gruppi proposti (${auto.length})</h2><p class="sub">Da cartelle in comune e dalle sezioni e dai progetti che hai già creato in Codex.</p>`
    + (auto.map(g => `<div class="scheda"><div class="riga"><div><b>${esc(g.nome)}</b> <span class="prova">${esc(g.prova)}</span>
        <div class="msg">${g.membri.map(titolo).join(" · ")}</div></div>
        <div><button class="primario" data-azione="crea-auto" data-gruppo="${esc(g.id)}">Crea gruppo</button>
        <button data-azione="decidi" data-decisione="rifiuta" data-arco="${esc(g.id)}">Rifiuta</button></div></div></div>`).join("")
      || `<div class="vuoto">Nessun gruppo automatico da valutare.</div>`)
    + `<h2>Collegamenti da confermare (${archi.length})</h2>`
    + (archi.length ? `<div class="controlli"><label><input type="checkbox" id="p-tutti"> tutti</label>
        <button data-azione="p-blocco" data-decisione="conferma">Conferma selezionati</button>
        <button data-azione="p-blocco" data-decisione="rifiuta">Rifiuta selezionati</button></div>` : "")
    + (archi.map(a => `<div class="scheda"><div class="riga"><label><input type="checkbox" class="p-sel" value="${esc(a.id)}">
        <b>${titolo(a.da)}</b> → <b>${titolo(a.a)}</b></label>
        <div><span class="conf">${esc(TIPI[a.tipo] || a.tipo)} · ${esc(CONF[a.confidenza])}</span>
        <button class="primario" data-azione="decidi" data-decisione="conferma" data-arco="${esc(a.id)}">Conferma</button>
        <button data-azione="decidi" data-decisione="rifiuta" data-arco="${esc(a.id)}">Rifiuta</button></div></div>
        <div class="prova">${esc(a.prova)}</div></div>`).join("") || `<div class="vuoto">Nessun collegamento da confermare.</div>`)
    + `<h2>Regole automatiche (${D.regole.length})</h2>
      <div class="form-riga">Se <select id="r-campo" aria-label="Campo"><option value="titolo">il titolo</option><option value="progetto">il progetto</option>
      <option value="strumento">lo strumento</option><option value="macchina">la macchina</option></select> contiene
      <input type="text" id="r-testo" placeholder="testo" aria-label="Testo"> metti nel gruppo
      <select id="r-gruppo" aria-label="Gruppo">${opzioniGruppi("", "— scegli")}</select><button data-azione="crea-regola">Crea regola</button></div>`
    + D.regole.map(r => `<div class="scheda"><div class="riga"><span>Se <b>${esc(r.campo)}</b> contiene “${esc(r.contiene)}” → <b>${esc(GR[r.gruppo]?.percorso || r.gruppo)}</b></span>
        <button data-azione="elimina-regola" data-regola="${esc(r.id)}">Elimina</button></div></div>`).join("")
    + `<h2>Decisioni prese (${prese.length})</h2>`
    + (prese.map(([id, dec]) => `<div class="scheda"><div class="riga"><span><span class="conf">${dec === "conferma" ? "confermato" : "rifiutato"}</span>
        <span class="cart">${esc(id)}</span></span><button data-azione="decidi" data-decisione="annulla_decisione" data-arco="${esc(id)}">Annulla</button></div></div>`).join("")
      || `<div class="vuoto">Ancora nessuna decisione.</div>`);
}

// --- 6. cronologia ------------------------------------------------------------------------------------------------------
function vistaCronologia(el, vis) {
  const ora = Date.now(), durata = U.giorni * 86400000, t0 = ora - durata;
  const voci = vis.map(s => {
    const fine = ms(s.ultima_attivita);
    let ini = ms(s.inizio);
    if (!(ini <= fine)) ini = fine - 10 * 60000;
    return { s, ini: Math.max(ini, t0), fine };
  }).filter(v => v.fine >= t0);
  const corsia = v => U.corsie === "gruppo" ? (v.s.gruppo_percorso || "Senza gruppo") : (v.s.macchina ? "@" + v.s.macchina : "cloud");
  const corsie = new Map();
  for (const v of voci.sort((a, b) => a.ini - b.ini)) { const k = corsia(v); if (!corsie.has(k)) corsie.set(k, []); corsie.get(k).push(v); }
  const larg = Math.max((el.clientWidth || 900) - 4, 760), ET = 150, X = t => ET + (t - t0) / durata * (larg - ET - 12);
  let y = 30, corpo = "";
  const H = 18, GAP = 4;
  for (const [k, lista] of [...corsie.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    const righe = [];
    for (const v of lista) {
      let r = righe.findIndex(fine => X(fine) + 6 < X(v.ini));
      if (r < 0) { r = righe.length; righe.push(0); }
      righe[r] = v.fine; v.riga = r;
    }
    const h = Math.max(1, righe.length) * (H + GAP) + 8;
    corpo += `<line class="griglia" x1="0" x2="${larg}" y1="${y + h}" y2="${y + h}"/><text x="6" y="${y + 16}" font-weight="700">${esc(corto(k, 22))}</text>`;
    for (const v of lista) {
      const x1 = X(v.ini), w = Math.max(5, X(v.fine) - x1), yy = y + 4 + v.riga * (H + GAP);
      corpo += `<g class="nodo" data-azione="apri" data-id="${esc(v.s.id)}"><title>${esc(v.s.titolo)} · ${esc(v.s.stato)} · ${quando(v.s.ultima_attivita)}</title>
        <rect class="barra-t ${classeStato(v.s.stato)}" x="${x1}" y="${yy}" width="${w}" height="${H}" rx="4"/>
        ${w > 70 ? `<text x="${x1 + 5}" y="${yy + 13}" fill="#fff" style="fill:#fff">${esc(corto(v.s.titolo, Math.floor(w / 7)))}</text>` : ""}</g>`;
    }
    y += h;
  }
  const passo = U.giorni <= 1 ? 3 * 3600000 : U.giorni <= 7 ? 86400000 : 5 * 86400000;
  let tacche = "";
  for (let t = Math.ceil(t0 / passo) * passo; t <= ora; t += passo) {
    const etichetta = U.giorni <= 1 ? new Date(t).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })
      : new Date(t).toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" });
    tacche += `<line class="griglia" x1="${X(t)}" x2="${X(t)}" y1="20" y2="${y}"/><text class="asse" x="${X(t) + 3}" y="14">${etichetta}</text>`;
  }
  el.innerHTML = `<div class="controlli">Corsie per <select data-cambia="ui" data-chiave="corsie" aria-label="Corsie">
      <option value="macchina"${U.corsie === "macchina" ? " selected" : ""}>macchina</option><option value="gruppo"${U.corsie === "gruppo" ? " selected" : ""}>gruppo</option></select>
    periodo <select data-cambia="ui" data-chiave="giorni" aria-label="Periodo"><option value="1"${U.giorni == 1 ? " selected" : ""}>24 ore</option>
      <option value="7"${U.giorni == 7 ? " selected" : ""}>7 giorni</option><option value="30"${U.giorni == 30 ? " selected" : ""}>30 giorni</option></select>
    <span class="sub">${voci.length} sessioni nel periodo; la barra va dall'inizio (se noto) all'ultima attività.</span></div>`
    + (voci.length ? `<div class="cronologia"><svg width="${larg}" height="${y + 10}" aria-label="Cronologia">${tacche}${corpo}
      <line class="adesso" x1="${X(ora)}" x2="${X(ora)}" y1="20" y2="${y}"/></svg></div>` : `<div class="vuoto">Nessuna sessione nel periodo.</div>`);
}

// --- 7. kanban --------------------------------------------------------------------------------------------------------
function colonnaDi(s) {
  if (s.colonna && D.colonne.includes(s.colonna)) return s.colonna;
  const mappa = { attiva: "in corso", "in lavoro": "in corso", bloccata: "in attesa", interrotta: "in attesa", "interrotta?": "in attesa",
    completata: "fatto", archiviata: "fatto" };
  const c = mappa[s.stato];
  return c && D.colonne.includes(c) ? c : D.colonne[0];
}

function vistaKanban(el, vis) {
  el.innerHTML = `<div class="controlli"><input type="text" id="k-colonne" value="${esc(D.colonne.join(", "))}" aria-label="Colonne separate da virgole" size="40">
    <button data-azione="salva-colonne">Salva colonne</button><span class="sub">La colonna iniziale è proposta dallo stato; trascina le carte o usa il menu.</span></div>
    <div class="kanban">${D.colonne.map(c => {
      const carte = vis.filter(s => colonnaDi(s) === c);
      return `<section class="colonna" data-colonna="${esc(c)}"><h3>${esc(c)} <span class="sub">${carte.length}</span></h3>
        ${carte.map(s => `<div class="carta" draggable="true" data-trascina="k:${esc(s.id)}">${chip(s)} ${s.priorita === "alta" ? '<span class="prio-alta">!</span>' : ""}
          <div><button class="titolo-link" data-azione="apri" data-id="${esc(s.id)}">${esc(s.titolo || s.id)}</button></div>
          <div class="msg">${esc(s.strumento)}${s.macchina ? " @" + esc(s.macchina) : ""} · ${quando(s.ultima_attivita)}</div>
          ${gruppoTag(s)}${s.prossima_azione ? `<div class="msg"><b>→ ${esc(s.prossima_azione)}</b></div>` : ""}
          <select data-cambia="colonna" data-id="${esc(s.id)}" aria-label="Colonna">${D.colonne.map(x => `<option${x === c ? " selected" : ""}>${esc(x)}</option>`).join("")}</select></div>`).join("")}
      </section>`;
    }).join("")}</div>`;
}

// --- 8. avvisi -------------------------------------------------------------------------------------------------------------
function vistaAvvisi(el) {
  el.innerHTML = D.avvisi.map(a => `<div class="scheda liv-${esc(a.livello)}"><div class="riga"><span>${a.livello === "attenzione" ? "⚠" : "ℹ"} ${esc(a.testo)}</span>
      ${a.sessione ? `<button class="titolo-link" data-azione="apri" data-id="${esc(a.sessione)}">${esc(PER[a.sessione]?.titolo || a.sessione)}</button>` : ""}
      ${a.tipo === "proposte" ? `<button data-azione="vista" data-vista="proposte">Apri le proposte</button>` : ""}</div></div>`).join("")
    || `<div class="vuoto">Nessun avviso.</div>`;
}

// --- pannello dettagli -------------------------------------------------------------------------------------------------------
function disegnaDettaglio() {
  const pannello = $("#dettaglio");
  const s = dettaglio && PER[dettaglio];
  if (!s) { pannello.hidden = true; return; }
  if (pannello.contains(document.activeElement) && pannello.dataset.id === s.id && document.activeElement.matches("input,textarea,select")) return;
  pannello.dataset.id = s.id;
  const titolo = id => esc(PER[id]?.titolo || id);
  const legami = D.archi.filter(a => a.da === s.id || a.a === s.id);
  const apri = s.id.startsWith("session_") ? ` · <a href="https://claude.ai/code/${encodeURIComponent(s.id)}" target="_blank" rel="noopener">apri in claude.ai</a>` : "";
  const altre = D.sessioni.filter(x => x.id !== s.id).sort((a, b) => String(a.titolo).localeCompare(String(b.titolo)));
  pannello.innerHTML = `<button class="chiudi" data-azione="chiudi" aria-label="Chiudi">✕</button>
    <h2>${esc(s.titolo || s.id)}</h2><div>${chip(s)} <b>${esc(s.strumento)}</b>${macchinaTag(s)}</div>
    <dl class="campi"><dt>Tipo</dt><dd>${esc(s.tipo)}${s.modello ? " · " + esc(s.modello) : ""}</dd>
      <dt>Progetto</dt><dd>${esc(s.progetto || "—")}</dd>
      ${s.sezione_codex ? `<dt>Sezione Codex</dt><dd>${esc(s.sezione_codex)}</dd>` : ""}
      ${s.progetto_codex ? `<dt>Progetto Codex</dt><dd>${esc(s.progetto_codex)}</dd>` : ""}<dt>Cartella</dt><dd class="cart">${esc(s.cartella || "—")}</dd>
      <dt>Inizio</dt><dd>${s.inizio ? new Date(s.inizio).toLocaleString("it-IT") : "—"}</dd><dt>Ultima attività</dt><dd>${quando(s.ultima_attivita)}</dd>
      <dt>Id</dt><dd class="cart">${esc(s.id)}${apri}</dd>
      ${s.ultimo_messaggio ? `<dt>Ultimo messaggio</dt><dd>${esc(s.ultimo_messaggio)}</dd>` : ""}
      ${s.riferimenti?.length ? `<dt>Cita</dt><dd class="cart">${s.riferimenti.map(esc).join(", ")}</dd>` : ""}</dl>
    <label>Gruppo <select data-cambia="sposta-sessione" data-id="${esc(s.id)}">${opzioniGruppi(s.gruppo_fonte === "manuale" ? s.gruppo : "_togli",
      s.gruppo_fonte === "regola" ? "— nessun gruppo manuale (ora per regola: " + esc(s.gruppo_percorso) + ")" : "— nessun gruppo", "_togli")}</select></label>
    <label>Prossima azione <input type="text" id="d-prossima" value="${esc(s.prossima_azione)}"></label>
    <label>Nota <textarea id="d-nota">${esc(s.nota)}</textarea></label>
    <label>Etichette (separate da virgole) <input type="text" id="d-etichette" value="${esc((s.etichette || []).join(", "))}"></label>
    <label>Priorità <select id="d-priorita">${["", "alta", "media", "bassa"].map(p => `<option value="${p}"${p === s.priorita ? " selected" : ""}>${p || "—"}</option>`).join("")}</select></label>
    <label>Colonna kanban <select id="d-colonna">${D.colonne.map(c => `<option${c === colonnaDi(s) ? " selected" : ""}>${esc(c)}</option>`).join("")}</select></label>
    <label><input type="checkbox" id="d-nascosta"${s.nascosta ? " checked" : ""} style="width:auto"> nascondi dalle viste</label>
    <p><button class="primario" data-azione="salva-dettaglio">Salva</button></p>
    <h2>Collegamenti (${legami.length})</h2><ul class="legami">${legami.map(a => {
      const esce = a.da === s.id, altro = esce ? a.a : a.da;
      const azioni = a.confidenza === "manuale" ? `<button data-azione="scollega" data-arco="${esc(a.id)}">Scollega</button>`
        : a.confidenza === "confermato" ? `<button data-azione="decidi" data-decisione="annulla_decisione" data-arco="${esc(a.id)}">Annulla conferma</button>`
        : a.confidenza === "certo" ? "" : `<button data-azione="decidi" data-decisione="conferma" data-arco="${esc(a.id)}">Conferma</button>
          <button data-azione="decidi" data-decisione="rifiuta" data-arco="${esc(a.id)}">Rifiuta</button>`;
      return `<li>${esce ? "questa" : `<button class="titolo-link" data-azione="apri" data-id="${esc(altro)}">${titolo(altro)}</button>`}
        → <i>${esc(TIPI[a.tipo] || a.tipo)}</i> → ${esce ? `<button class="titolo-link" data-azione="apri" data-id="${esc(altro)}">${titolo(altro)}</button>` : "questa"}
        <span class="conf">${esc(CONF[a.confidenza])}</span> ${azioni}<div class="prova">${esc(a.prova || "")}</div></li>`;
    }).join("") || "<li>Nessuno.</li>"}</ul>
    <label>Collega a <select id="d-altra">${altre.map(x => `<option value="${esc(x.id)}">${esc(corto(x.titolo || x.id, 50))}${x.macchina ? " @" + esc(x.macchina) : ""}</option>`).join("")}</select></label>
    <label>Tipo <select id="d-tipo">${TIPI_MANUALI.map(t => `<option value="${t}">${TIPI[t]}</option>`).join("")}</select></label>
    <label>Verso <select id="d-verso"><option value="esce">questa → altra</option><option value="entra">altra → questa</option></select></label>
    <p><button data-azione="collega">Aggiungi collegamento</button></p>`;
  pannello.hidden = false;
}

// --- azioni ---------------------------------------------------------------------------------------------------------------
function opsSposta(id, gruppo) {
  return gruppo && gruppo !== "_togli" ? [{ op: "aggiungi", sessione: id, gruppo }] : [{ op: "togli", sessione: id }];
}

document.addEventListener("click", e => {
  const t = e.target.closest("[data-azione]");
  if (!t) return;
  const a = t.dataset.azione, id = t.dataset.id;
  if (t.closest("#tela") && $("#tela").dataset.trascinato) return;
  switch (a) {
    case "vista": U.vista = t.dataset.vista; salvaUI(); disegna(); break;
    case "apri": dettaglio = id; disegnaDettaglio(); $("#tela")?.querySelectorAll(".nodo").forEach(n => n.classList.toggle("attivo", n.dataset.id === id)); break;
    case "chiudi": dettaglio = null; disegnaDettaglio(); break;
    case "zoom": telaAttiva?.zoom(+t.dataset.f); break;
    case "adatta": if (telaAttiva?.limiti) telaAttiva.adatta(...telaAttiva.limiti); else if (telaAttiva) { const r = $("#tela").getBoundingClientRect(); Object.assign(telaAttiva.st, { x: r.width / 2, y: r.height / 2, k: 0.8 }); telaAttiva.applica(); } break;
    case "forze-pausa": if (!tele.forzePausa) { tele.ferma?.(); t.textContent = "Riprendi"; } else { tele.riscalda?.(); t.textContent = "Pausa"; } break;
    case "forze-rimescola": for (const k of Object.keys(posForze)) delete posForze[k]; tele.forzeAlfa = 1; tele.forzePausa = false; disegna(); break;
    case "decidi": invia([{ op: t.dataset.decisione, arco: t.dataset.arco }], { conferma: "Confermato", rifiuta: "Rifiutato", annulla_decisione: "Decisione annullata" }[t.dataset.decisione]); break;
    case "scollega": invia([{ op: "scollega", id: t.dataset.arco }], "Collegamento tolto"); break;
    case "p-blocco": {
      const scelti = [...document.querySelectorAll(".p-sel:checked")].map(x => ({ op: t.dataset.decisione, arco: x.value }));
      if (scelti.length) invia(scelti, `${scelti.length} decisioni salvate`); else avvisa("Nessun collegamento selezionato");
      break;
    }
    case "crea-auto": {
      const g = D.gruppi_auto.find(x => x.id === t.dataset.gruppo), nuovo = nuovoId("g-");
      const liberi = g.membri.filter(m => !PER[m]?.gruppo || PER[m].gruppo_fonte !== "manuale");
      invia([{ op: "crea_gruppo", id: nuovo, nome: g.nome_proposto || g.nome }, ...liberi.map(m => ({ op: "aggiungi", sessione: m, gruppo: nuovo })),
        { op: "conferma", arco: g.id }], `Gruppo creato con ${liberi.length} sessioni`);
      break;
    }
    case "crea-gruppo": {
      const nome = $("#a-nome").value.trim();
      if (!nome) { avvisa("Scrivi un nome per il gruppo"); break; }
      const op = { op: "crea_gruppo", id: nuovoId("g-"), nome };
      if ($("#a-genitore").value) op.genitore = $("#a-genitore").value;
      invia([op], "Gruppo creato");
      break;
    }
    case "rinomina-gruppo": {
      e.preventDefault();
      const nome = prompt("Nuovo nome del gruppo", GR[t.dataset.gruppo]?.nome || "");
      if (nome && nome.trim()) invia([{ op: "rinomina_gruppo", id: t.dataset.gruppo, nome: nome.trim() }], "Gruppo rinominato");
      break;
    }
    case "elimina-gruppo":
      e.preventDefault();
      if (confirm(`Eliminare il gruppo “${GR[t.dataset.gruppo]?.nome}”? Sessioni e sottogruppi passano al gruppo superiore.`))
        invia([{ op: "elimina_gruppo", id: t.dataset.gruppo }], "Gruppo eliminato");
      break;
    case "crea-regola": {
      const testo = $("#r-testo").value.trim(), gruppo = $("#r-gruppo").value;
      if (!testo || !gruppo) { avvisa("Servono il testo e il gruppo"); break; }
      invia([{ op: "crea_regola", id: nuovoId("r-"), campo: $("#r-campo").value, contiene: testo, gruppo }], "Regola creata");
      break;
    }
    case "elimina-regola": invia([{ op: "elimina_regola", id: t.dataset.regola }], "Regola eliminata"); break;
    case "salva-colonne": {
      const col = $("#k-colonne").value.split(",").map(x => x.trim()).filter(Boolean);
      if (col.length) invia([{ op: "imposta_colonne", colonne: col }], "Colonne salvate");
      break;
    }
    case "salva-dettaglio": {
      const s = PER[dettaglio], ops = [];
      const nuovi = { prossima_azione: $("#d-prossima").value.trim(), nota: $("#d-nota").value.trim(),
        etichette: $("#d-etichette").value.split(",").map(x => x.trim()).filter(Boolean), priorita: $("#d-priorita").value,
        colonna: $("#d-colonna").value, nascosta: $("#d-nascosta").checked };
      for (const [campo, v] of Object.entries(nuovi)) {
        const vecchio = campo === "colonna" ? (s.colonna || "") : s[campo];
        if (JSON.stringify(v) !== JSON.stringify(vecchio) && !(campo === "colonna" && !s.colonna && v === colonnaDi(s)))
          ops.push({ op: "imposta", sessione: s.id, campo, valore: v });
      }
      $("#dettaglio").contains(document.activeElement) && document.activeElement.blur();
      if (ops.length) invia(ops, "Salvato"); else avvisa("Nessuna modifica");
      break;
    }
    case "collega": {
      const altra = $("#d-altra").value, tipo = $("#d-tipo").value, esce = $("#d-verso").value === "esce";
      invia([{ op: "collega", da: esce ? dettaglio : altra, a: esce ? altra : dettaglio, tipo }], "Collegamento aggiunto");
      break;
    }
    case "b-sposta": { const g = $("#b-gruppo").value; if (!g) { avvisa("Scegli un gruppo"); break; }
      invia([...selezionati].flatMap(id => opsSposta(id, g)), `${selezionati.size} sessioni spostate`); break; }
    case "b-togli": invia([...selezionati].map(id => ({ op: "togli", sessione: id })), "Tolte dal gruppo"); break;
    case "b-nuovo": { const nome = $("#b-nuovo").value.trim(); if (!nome) { avvisa("Scrivi un nome"); break; }
      const g = nuovoId("g-");
      invia([{ op: "crea_gruppo", id: g, nome }, ...[...selezionati].map(id => ({ op: "aggiungi", sessione: id, gruppo: g }))], "Gruppo creato"); break; }
    case "b-collega": {
      const lista = [...selezionati].map(id => PER[id]).sort((x, y) => String(x.ultima_attivita).localeCompare(String(y.ultima_attivita)));
      if (lista.length < 2) { avvisa("Seleziona almeno due sessioni"); break; }
      const tipo = $("#b-tipo").value;
      invia(lista.slice(1).map((s, i) => ({ op: "collega", da: lista[i].id, a: s.id, tipo })), `${lista.length - 1} collegamenti aggiunti`); break;
    }
    case "b-etichetta": { const et = $("#b-etichetta").value.trim(); if (!et) break;
      invia([...selezionati].map(id => ({ op: "imposta", sessione: id, campo: "etichette", valore: [...new Set([...(PER[id].etichette || []), et])] })), "Etichetta aggiunta"); break; }
    case "b-nascondi": invia([...selezionati].map(id => ({ op: "imposta", sessione: id, campo: "nascosta", valore: true })), "Nascoste"); selezionati.clear(); break;
    case "b-svuota": selezionati.clear(); disegna(); break;
  }
});

// pulsanti e menu dentro l'intestazione di un gruppo non devono aprire o chiudere il gruppo
document.addEventListener("click", e => {
  if (e.target.closest("summary") && e.target.closest("button,select")) e.preventDefault();
}, true);

document.addEventListener("change", e => {
  const t = e.target;
  if (t.id === "sel-tutte") { visibili().forEach(s => (t.checked ? selezionati.add(s.id) : selezionati.delete(s.id))); disegna(); return; }
  if (t.id === "p-tutti") { document.querySelectorAll(".p-sel").forEach(x => (x.checked = t.checked)); return; }
  if (["macchina", "gruppo"].includes(t.id)) { U[t.id] = t.value; salvaUI(); disegna(); return; }
  if (["interne", "ferme", "nascoste"].includes(t.id)) { U[t.id] = t.checked; salvaUI(); disegna(); return; }
  switch (t.dataset.cambia) {
    case "sel": t.checked ? selezionati.add(t.dataset.id) : selezionati.delete(t.dataset.id); disegna(); break;
    case "ui": U[t.dataset.chiave] = t.type === "checkbox" ? t.checked : (t.dataset.chiave === "giorni" ? +t.value : t.value); salvaUI(); disegna(); break;
    case "sposta-sessione": if (t.value) invia(opsSposta(t.dataset.id, t.value), "Sessione spostata"); break;
    case "sposta-gruppo": if (t.value) invia([{ op: "sposta_gruppo", id: t.dataset.gruppo, genitore: t.value === "_radice" ? "" : t.value }], "Gruppo spostato"); break;
    case "colonna": invia([{ op: "imposta", sessione: t.dataset.id, campo: "colonna", valore: t.value }], "Carta spostata"); break;
  }
});

document.addEventListener("toggle", e => {
  const d = e.target;
  if (!d.matches?.("details[data-gruppo]")) return;
  const g = d.dataset.gruppo, chiusi = new Set(U.chiusi);
  d.open ? chiusi.delete(g) : chiusi.add(g);
  U.chiusi = [...chiusi]; salvaUI();
}, true);

// trascina e rilascia: sessioni e gruppi nell'albero, carte nel kanban
document.addEventListener("dragstart", e => {
  const t = e.target.closest?.("[data-trascina]");
  if (!t) return;
  e.dataTransfer.setData("text/plain", t.dataset.trascina);
  e.dataTransfer.effectAllowed = "move";
  trascina = true;
  e.stopPropagation();
});
document.addEventListener("dragend", () => { trascina = false; document.querySelectorAll(".bersaglio").forEach(x => x.classList.remove("bersaglio")); });
document.addEventListener("dragover", e => {
  const b = e.target.closest?.("[data-bersaglio], .colonna");
  if (!b) return;
  e.preventDefault();
  document.querySelectorAll(".bersaglio").forEach(x => x !== b && x.classList.remove("bersaglio"));
  b.classList.add("bersaglio");
});
document.addEventListener("drop", e => {
  const b = e.target.closest?.("[data-bersaglio], .colonna");
  if (!b) return;
  e.preventDefault();
  const dato = e.dataTransfer.getData("text/plain"), [tipo, id] = [dato.slice(0, 1), dato.slice(2)];
  trascina = false;
  if (b.classList.contains("colonna")) {
    if (tipo === "k") invia([{ op: "imposta", sessione: id, campo: "colonna", valore: b.dataset.colonna }], "Carta spostata");
    return;
  }
  const gruppo = b.dataset.bersaglio.slice(2);
  if (tipo === "s") invia(opsSposta(id, gruppo), "Sessione spostata");
  else if (tipo === "g" && id !== gruppo) invia([{ op: "sposta_gruppo", id, genitore: gruppo }], "Gruppo spostato");
});

// filtri, tema, aggiornamento
$("#testo").addEventListener("input", e => { U.testo = e.target.value; salvaUI(); disegna(); });
$("#agg").addEventListener("click", carica);
const TEMI = ["", "light", "dark"], NOMI_TEMA = { "": "◐ automatico", light: "☀ chiaro", dark: "☾ scuro" };
function applicaTema() {
  if (U.tema) document.documentElement.dataset.theme = U.tema; else delete document.documentElement.dataset.theme;
  $("#tema").textContent = NOMI_TEMA[U.tema] || NOMI_TEMA[""];
}
$("#tema").addEventListener("click", () => { U.tema = TEMI[(TEMI.indexOf(U.tema) + 1) % TEMI.length]; salvaUI(); applicaTema(); });
document.addEventListener("keydown", e => { if (e.key === "Escape" && dettaglio) { dettaglio = null; disegnaDettaglio(); } });
applicaTema();
carica();
setInterval(() => {
  const occupato = trascina || ($("#dettaglio").contains(document.activeElement) && document.activeElement.matches("input,textarea,select"))
    || document.activeElement?.matches?.("#a-nome,#b-nuovo,#b-etichetta,#r-testo,#k-colonne,#testo");
  if (!occupato) carica();
}, 30000);
