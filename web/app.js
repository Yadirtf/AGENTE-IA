/* =====================================================================
   AMPARO — lógica de la interfaz
   ===================================================================== */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch (_) {} };
const leer = (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } };

const estado = {
  conversacion: null, modo: "sencillo", vozAuto: leer("amparo-voz") !== "0", ocupado: false,
  fuentes: [], expediente: null, folio: 0, sistema: null, ultimoUsuario: [],
};

function toast(msg, ms = 3200) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("visible");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("visible"), ms);
}

async function api(ruta, opciones = {}) {
  const r = await fetch(ruta, { headers: { "Content-Type": "application/json" }, ...opciones });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.headers.get("content-type")?.includes("json") ? r.json() : r;
}

/* ---------- Markdown mínimo con citas [n] ---------- */
function md(texto) {
  const inline = (s) => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[(\d{1,2})\]/g, '<span class="cita" data-n="$1" tabindex="0">$1</span>');
  const lineas = texto.split("\n");
  let html = "", lista = null;
  const cerrar = () => { if (lista) { html += `</${lista}>`; lista = null; } };
  for (const l of lineas) {
    const ul = l.match(/^\s*[-*•]\s+(.*)/), ol = l.match(/^\s*\d+[.)]\s+(.*)/), h = l.match(/^#{1,4}\s+(.*)/);
    if (ul || ol) {
      const tipo = ul ? "ul" : "ol";
      if (lista !== tipo) { cerrar(); html += `<${tipo}>`; lista = tipo; }
      html += `<li>${inline((ul || ol)[1])}</li>`;
    } else if (h) { cerrar(); html += `<p><strong>${inline(h[1])}</strong></p>`; }
    else if (l.trim()) { cerrar(); html += `<p>${inline(l)}</p>`; }
    else cerrar();
  }
  cerrar();
  return html;
}

/* =====================================================================
   Cabecera: fecha, estado del sistema, tema, modo
   ===================================================================== */
$("#fecha-hoy").textContent = new Date().toLocaleDateString("es-CO", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

async function cargarEstado() {
  try {
    const e = await api("/api/estado");
    estado.sistema = e;
    const p = (ok, txt, titulo) => `<span class="pastilla ${ok === true ? "ok" : ok === "medio" ? "medio" : "mal"}" title="${esc(titulo)}"><i></i>${esc(txt)}</span>`;
    $("#estado").innerHTML = [
      p(e.llm.llm_listo, e.llm.modelo, e.llm.proveedor === "ollama" ? "Modelo local vía Ollama" : "Modelo por API"),
      p(e.llm.embed_listo, "EmbeddingGemma", "Embeddings de 768 dimensiones"),
      p(e.db, `pgvector · ${e.fragmentos ?? 0} frag.`, e.db ? "PostgreSQL conectado" : (e.db_error || "Sin conexión")),
      p(e.stt ? true : "medio", `Whisper ${e.whisper}`, e.stt ? "faster-whisper local" : "Usará el reconocimiento del navegador"),
      p(e.tts ? true : "medio", e.tts ? "Piper" : "Voz navegador", e.tts ? "Piper TTS local" : "Piper no instalado: voz del navegador"),
    ].join("");
  } catch (_) {
    $("#estado").innerHTML = `<span class="pastilla mal"><i></i>Servidor no disponible</span>`;
  }
}

const temaGuardado = leer("amparo-tema");
if (temaGuardado) document.documentElement.dataset.tema = temaGuardado;
$("#btn-tema").addEventListener("click", () => {
  const nuevo = document.documentElement.dataset.tema === "noche" ? "dia" : "noche";
  document.documentElement.dataset.tema = nuevo; guardar("amparo-tema", nuevo);
  $("#btn-tema").textContent = nuevo === "noche" ? "☀" : "☾";
});
$$(".interruptor button").forEach((b) => b.addEventListener("click", () => {
  $$(".interruptor button").forEach((x) => x.classList.toggle("activo", x === b));
  estado.modo = b.dataset.modo; toast(`Lenguaje ${b.textContent.toLowerCase()}`);
}));
const btnVoz = $("#btn-voz-auto");
const pintarVoz = () => { btnVoz.setAttribute("aria-pressed", estado.vozAuto); btnVoz.textContent = estado.vozAuto ? "🔊" : "🔈"; };
pintarVoz();
btnVoz.addEventListener("click", () => { estado.vozAuto = !estado.vozAuto; guardar("amparo-voz", estado.vozAuto ? "1" : "0"); pintarVoz(); toast(estado.vozAuto ? "Leeré las respuestas en voz alta" : "Respuestas solo en texto"); if (!estado.vozAuto) callar(); });

/* =====================================================================
   Pestañas
   ===================================================================== */
const alAbrir = {};
function abrir(vista) {
  $$(".pestanas button").forEach((b) => b.classList.toggle("activa", b.dataset.vista === vista));
  $$(".vista").forEach((v) => v.classList.toggle("activa", v.id === `vista-${vista}`));
  alAbrir[vista]?.();
}
$$(".pestanas button").forEach((b) => b.addEventListener("click", () => abrir(b.dataset.vista)));

/* =====================================================================
   Consulta
   ===================================================================== */
const EJEMPLOS = [
  ["Trabajo", "#2F5D50", "Me despidieron sin justa causa después de tres años"],
  ["Salud", "#2C7A7B", "La EPS no me entrega un medicamento que me ordenó el médico"],
  ["Arriendo", "#5B4B8A", "El dueño de la casa me quiere subir el arriendo un 20 %"],
  ["Familia", "#3D6B8C", "El papá de mi hijo no da la cuota alimentaria"],
  ["Consumidor", "#B0702C", "Compré un celular por internet y me arrepentí"],
  ["Petición", "#7A1F2B", "La alcaldía lleva un mes sin responder mi solicitud"],
];
$("#fichas").innerHTML = EJEMPLOS.map(([a, c, t]) => `<button class="ficha" style="--c:${c}"><small>${a}</small><span>${esc(t)}</span></button>`).join("");
$$(".ficha").forEach((f) => f.addEventListener("click", () => enviar($("span", f).textContent)));

const entrada = $("#entrada");
entrada.addEventListener("input", () => { entrada.style.height = "auto"; entrada.style.height = Math.min(entrada.scrollHeight, 160) + "px"; });
entrada.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#redactor").requestSubmit(); } });
$("#redactor").addEventListener("submit", (e) => { e.preventDefault(); const t = entrada.value.trim(); if (t) { entrada.value = ""; entrada.style.height = "auto"; enviar(t); } });

const hilo = $("#hilo");
const bajar = () => { hilo.scrollTop = hilo.scrollHeight; };

function agregarUsuario(texto, canal) {
  $("#bienvenida")?.remove();
  const d = document.createElement("div");
  d.className = "msg msg--usuario";
  d.innerHTML = `<div class="burbuja">${esc(texto)}<span class="canal">${canal === "voz" ? "🎙 dictado por voz" : "escrito"}</span></div>`;
  hilo.appendChild(d); bajar();
}

function nuevoFolio() {
  estado.folio++;
  const d = document.createElement("div");
  d.className = "msg msg--agente";
  const hora = new Date().toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  d.innerHTML = `<article class="folio"><span class="folio__num">${estado.folio}</span>
    <div class="folio__cab"><span>Amparo · folio ${estado.folio}</span><span>${hora}</span></div>
    <div class="folio__cuerpo"><div class="pensando"><span class="pluma"></span>Consultando la norma…</div></div></article>`;
  hilo.appendChild(d); bajar();
  return d;
}

function etapa(nombre, est, ms) {
  const n = $(`.nodo[data-etapa="${nombre}"]`); if (!n) return;
  n.classList.toggle("activo", est === "inicio");
  n.classList.toggle("hecho", est === "fin");
  if (est === "fin" && ms != null) $("small", n).textContent = ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}
function reiniciarTuberia(canal) {
  const base = { voz: "micrófono", stt: "STT", embedding: "embedding", pgvector: "búsqueda", llm: "razona", tts: "TTS" };
  $$(".nodo").forEach((n) => { n.classList.remove("activo", "hecho"); $("small", n).textContent = base[n.dataset.etapa]; });
  if (canal !== "voz") { $('.nodo[data-etapa="voz"] small').textContent = "teclado"; }
}

/* Lector de Server-Sent Events sobre fetch POST */
async function* eventos(resp) {
  const lector = resp.body.getReader(), dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await lector.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const bloque = buf.slice(0, i); buf = buf.slice(i + 2);
      let tipo = "message", datos = "";
      for (const l of bloque.split("\n")) {
        if (l.startsWith("event:")) tipo = l.slice(6).trim();
        else if (l.startsWith("data:")) datos += l.slice(5).trim();
      }
      yield { tipo, datos: datos ? JSON.parse(datos) : null };
    }
  }
}

async function enviar(texto, canal = "texto", msStt = null) {
  if (estado.ocupado) return toast("Espere a que termine la respuesta anterior");
  estado.ocupado = true; $("#enviar").disabled = true; callar();
  if (canal !== "voz") reiniciarTuberia(canal);
  estado.ultimoUsuario.push(texto);
  agregarUsuario(texto, canal);
  const nodo = nuevoFolio();
  const cuerpo = $(".folio__cuerpo", nodo);
  let respuesta = "", primero = true, metricas = null;
  try {
    const resp = await fetch("/api/consulta", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto, conversacion_id: estado.conversacion, modo: estado.modo, canal, ms_stt: msStt }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    for await (const { tipo, datos } of eventos(resp)) {
      if (tipo === "conversacion") { estado.conversacion = datos.id; $("#exp-num").textContent = numeroExpediente(datos.id); }
      else if (tipo === "etapa") etapa(datos.etapa, datos.estado, datos.ms);
      else if (tipo === "emergencia") mostrarEmergencia(datos);
      else if (tipo === "fuentes") pintarFuentes(datos);
      else if (tipo === "expediente") pintarExpediente(datos);
      else if (tipo === "token") {
        if (primero) { cuerpo.innerHTML = ""; primero = false; }
        respuesta += datos;
        cuerpo.innerHTML = md(respuesta) + '<span class="cursor"></span>';
        bajar();
      } else if (tipo === "fin") metricas = datos.metricas;
      else if (tipo === "error") throw new Error(datos.mensaje);
    }
    cuerpo.innerHTML = md(respuesta);
    enlazarCitas(cuerpo);
    pieFolio(nodo, respuesta);
    if (metricas) pintarMetricas(metricas);
    if (estado.vozAuto && respuesta) hablar(respuesta);
  } catch (err) {
    cuerpo.innerHTML = `<p><strong>No pude responder</strong></p><p>${esc(err.message)}</p>`;
    toast("Revise que Ollama y PostgreSQL estén encendidos");
  } finally {
    estado.ocupado = false; $("#enviar").disabled = false;
  }
}

function numeroExpediente(id) {
  const n = parseInt(id.replace(/-/g, "").slice(0, 6), 16) % 10000;
  return `${new Date().getFullYear()}-${String(n).padStart(4, "0")}`;
}

function pieFolio(nodo, texto) {
  const pie = document.createElement("div");
  pie.className = "folio__pie";
  pie.innerHTML = `<button class="chip-btn" data-a="oir">▶ Escuchar</button><button class="chip-btn" data-a="copiar">Copiar</button><button class="chip-btn" data-a="doc">✎ Convertir en documento</button><button class="chip-btn" data-a="plazo">⌛ Calcular plazo</button>`;
  $(".folio", nodo).appendChild(pie);
  pie.addEventListener("click", (e) => {
    const a = e.target.dataset.a;
    if (a === "oir") hablar(texto);
    if (a === "copiar") navigator.clipboard?.writeText(texto).then(() => toast("Respuesta copiada"));
    if (a === "doc") desdeConversacion();
    if (a === "plazo") abrir("terminos");
  });
}

function enlazarCitas(raiz) {
  $$(".cita", raiz).forEach((c) => {
    const n = +c.dataset.n;
    const marcar = (on) => $$(".fuente").forEach((f) => f.classList.toggle("resaltada", on && +f.dataset.n === n));
    c.addEventListener("mouseenter", () => marcar(true));
    c.addEventListener("mouseleave", () => marcar(false));
    c.addEventListener("click", () => {
      const f = $(`.fuente[data-n="${n}"]`);
      if (f) { f.scrollIntoView({ behavior: "smooth", block: "center" }); $("details", f).open = true; marcar(true); setTimeout(() => marcar(false), 1800); }
      else { const x = estado.fuentes[n - 1]; if (x) toast(`[${n}] ${x.titulo} — ${x.fuente}`, 5000); }
    });
  });
}

function pintarFuentes(lista) {
  estado.fuentes = lista;
  $("#fuentes-meta").textContent = `${lista.length} fragmentos · híbrido RRF`;
  $("#fuentes").innerHTML = lista.map((f, i) => `
    <div class="fuente" data-n="${i + 1}" style="animation-delay:${i * 70}ms">
      <div class="fuente__cab"><span class="fuente__n">${i + 1}</span>
        <div><div class="fuente__titulo">${esc(f.titulo)}</div><div class="fuente__sec">${esc(f.seccion)}</div></div></div>
      <div class="fuente__norma">${esc(f.fuente)}</div>
      <div class="medidor"><div class="pista"><span style="width:0" data-w="${Math.max(4, Math.round(f.similitud * 100))}"></span></div><small>sim ${f.similitud.toFixed(2)}</small></div>
      <details><summary>Ver fragmento${f.rango_lex ? " · coincide por palabras" : ""}</summary><p>${esc(f.contenido)}</p></details>
    </div>`).join("") || `<p class="nota">No se encontraron fuentes relevantes.</p>`;
  requestAnimationFrame(() => $$(".fuente .pista span").forEach((s) => (s.style.width = s.dataset.w + "%")));
}

function pintarExpediente(x) {
  estado.expediente = x;
  const a = x.area;
  if (a) {
    $("#exp-area").innerHTML = `<span class="simbolo" style="color:${a.color}">${esc(a.simbolo)}</span>${esc(a.nombre)}`;
    const est = $("#exp-estampa");
    est.textContent = { critica: "Prioridad", alta: "Urgente", media: "Atender", baja: "Orientado" }[x.urgencia.nivel] || "Orientado";
    est.style.color = x.urgencia.nivel === "baja" ? "var(--salvia)" : "var(--lacre)";
    est.hidden = false; est.classList.remove("golpe"); void est.offsetWidth; est.classList.add("golpe");
  }
  $("#exp-urgencia").dataset.nivel = x.urgencia.nivel;
  $("#exp-urgencia-razon").textContent = `${x.urgencia.nivel.toUpperCase()} · ${x.urgencia.razones.join(", ")}`;
  $("#exp-distribucion").innerHTML = x.distribucion.map((d) => `
    <div class="barra"><span class="sim" style="color:${d.color}">${esc(d.simbolo)}</span><span class="nombre">${esc(d.nombre)}</span>
    <div class="pista"><span style="width:0;background:${d.color}" data-w="${Math.round(d.probabilidad * 100)}"></span></div>
    <span class="pct">${Math.round(d.probabilidad * 100)}%</span></div>`).join("");
  requestAnimationFrame(() => $$("#exp-distribucion .pista span").forEach((s) => (s.style.width = s.dataset.w + "%")));
  $("#exp-ruta").innerHTML = x.ruta.map((r, i) => `<li style="animation-delay:${i * 90}ms"><b>${esc(r.titulo)}</b><p>${esc(r.detalle)}</p>${r.plazo ? `<span class="plazo">${esc(r.plazo)}</span>` : ""}</li>`).join("") || '<li class="nota">Sin ruta para esta área.</li>';
  $("#exp-entidades").innerHTML = x.entidades.map((e) => `<li><b>${esc(e.nombre)}</b>${/^\d{3}$/.test(e.contacto) ? `<a href="tel:${e.contacto}">☎ ${e.contacto}</a>` : `<span class="nota">${esc(e.contacto || e.municipio)}</span>`}</li>`).join("");
}

function pintarMetricas(m) {
  const f = (v) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`);
  $("#metricas-turno").innerHTML = [
    ["Primer token", m.primer_token], ["Generación", m.llm], ["Recuperación", m.pgvector], ["Total", m.total],
  ].map(([t, v]) => `<div><b>${f(v)}</b><small>${t}</small></div>`).join("");
}

function mostrarEmergencia(e) {
  $("#emergencia-msg").textContent = e.mensaje;
  $("#emergencia-lineas").innerHTML = e.lineas.map((l) => `<a href="tel:${l.numero}">${l.numero}<small>${esc(l.nombre)}</small></a>`).join("");
  $("#emergencia").hidden = false;
  document.documentElement.style.setProperty("--alerta", $("#emergencia").offsetHeight + "px");
}

function limpiarConsulta() {
  estado.conversacion = null; estado.folio = 0; estado.ultimoUsuario = [];
  hilo.innerHTML = ""; $("#fuentes").innerHTML = '<p class="nota">Las fuentes aparecerán aquí.</p>';
  $("#metricas-turno").innerHTML = ""; $("#exp-num").textContent = "—";
  $("#exp-area").innerHTML = '<span class="vacio">Sin clasificar</span>'; $("#exp-estampa").hidden = true;
}

/* =====================================================================
   Voz: grabación + visualización + STT + TTS
   ===================================================================== */
const mic = $("#microfono"), lienzo = $("#onda"), ctx2d = lienzo.getContext("2d");
let grabador = null, trozos = [], audioCtx = null, analizador = null, animacion = null, flujo = null, reproductor = null;
let silencioDesde = null, huboVoz = false;

function asegurarAudio() {
  audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === "suspended") audioCtx.resume();
}

function dibujar(fuenteDatos, color) {
  cancelAnimationFrame(animacion);
  const datos = new Uint8Array(64);
  const W = lienzo.width, R = 46;
  const paso = () => {
    ctx2d.clearRect(0, 0, W, W);
    let nivel = 0;
    if (fuenteDatos) { fuenteDatos.getByteFrequencyData(datos); nivel = datos.reduce((a, b) => a + b, 0) / datos.length / 255; }
    else { const t = performance.now() / 400; for (let i = 0; i < 64; i++) datos[i] = 90 + 70 * Math.sin(t + i * 0.5) * Math.sin(t * 0.7 + i); nivel = 0.3; }
    ctx2d.strokeStyle = color; ctx2d.lineCap = "round"; ctx2d.lineWidth = 2.4;
    for (let i = 0; i < 48; i++) {
      const ang = (i / 48) * Math.PI * 2 - Math.PI / 2;
      const v = datos[i % 64] / 255, largo = 4 + v * 26;
      ctx2d.globalAlpha = 0.35 + v * 0.65;
      ctx2d.beginPath();
      ctx2d.moveTo(W / 2 + Math.cos(ang) * R, W / 2 + Math.sin(ang) * R);
      ctx2d.lineTo(W / 2 + Math.cos(ang) * (R + largo), W / 2 + Math.sin(ang) * (R + largo));
      ctx2d.stroke();
    }
    ctx2d.globalAlpha = 1;
    if (grabador?.state === "recording") vigilarSilencio(nivel);
    animacion = requestAnimationFrame(paso);
  };
  paso();
}
function detenerDibujo() { cancelAnimationFrame(animacion); ctx2d.clearRect(0, 0, lienzo.width, lienzo.height); }

function vigilarSilencio(nivel) { // corte automático tras 1,8 s de silencio
  if (nivel > 0.09) { huboVoz = true; silencioDesde = null; }
  else if (huboVoz) { silencioDesde ??= performance.now(); if (performance.now() - silencioDesde > 1800) pararGrabacion(); }
}

async function empezarGrabacion() {
  callar();
  try { flujo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
  catch (_) { return toast("No tengo permiso para usar el micrófono"); }
  asegurarAudio();
  analizador = audioCtx.createAnalyser(); analizador.fftSize = 128;
  audioCtx.createMediaStreamSource(flujo).connect(analizador);
  trozos = []; huboVoz = false; silencioDesde = null;
  grabador = new MediaRecorder(flujo);
  grabador.ondataavailable = (e) => e.data.size && trozos.push(e.data);
  grabador.onstop = procesarAudio;
  grabador.start();
  reiniciarTuberia("voz"); etapa("voz", "inicio");
  mic.classList.add("grabando"); $("#ayuda-voz").textContent = "Escuchando… toque de nuevo para terminar";
  dibujar(analizador, getComputedStyle(document.documentElement).getPropertyValue("--lacre").trim());
}

function pararGrabacion() {
  if (grabador?.state === "recording") grabador.stop();
  flujo?.getTracks().forEach((t) => t.stop());
  mic.classList.remove("grabando"); detenerDibujo();
}

async function procesarAudio() {
  const blob = new Blob(trozos, { type: grabador.mimeType || "audio/webm" });
  etapa("voz", "fin", null); $('.nodo[data-etapa="voz"] small').textContent = `${(blob.size / 1024).toFixed(0)} KB`;
  if (!huboVoz && blob.size < 6000) { $("#ayuda-voz").textContent = "No escuché nada. Intente de nuevo."; return; }
  mic.classList.add("procesando"); etapa("stt", "inicio"); $("#ayuda-voz").textContent = "Transcribiendo con Whisper…";
  try {
    const fd = new FormData(); fd.append("audio", blob, "voz.webm");
    const r = await fetch("/api/stt", { method: "POST", body: fd });
    if (r.status === 501) throw new Error("sin-stt");
    if (!r.ok) throw new Error(await r.text());
    const { texto, ms } = await r.json();
    etapa("stt", "fin", ms);
    if (!texto) { toast("No entendí el audio, ¿puede repetirlo?"); return; }
    enviar(texto, "voz", ms);
  } catch (e) {
    etapa("stt", "fin");
    toast(e.message === "sin-stt" ? "Whisper no está instalado en el servidor" : "Error al transcribir: " + e.message);
  } finally {
    mic.classList.remove("procesando"); $("#ayuda-voz").textContent = "Toque el sello para hablar · Shift+Enter: nueva línea";
  }
}

/* Respaldo: reconocimiento de voz del navegador (si el servidor no tiene Whisper) */
function dictadoNavegador() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return toast("Este navegador no permite dictado por voz");
  const r = new SR(); r.lang = "es-CO"; r.interimResults = true;
  mic.classList.add("grabando"); dibujar(null, "#9E2E3A"); reiniciarTuberia("voz"); etapa("voz", "inicio");
  const t0 = performance.now();
  r.onresult = (e) => { entrada.value = [...e.results].map((x) => x[0].transcript).join(" "); };
  r.onend = () => { mic.classList.remove("grabando"); detenerDibujo(); etapa("voz", "fin"); etapa("stt", "fin", Math.round(performance.now() - t0));
    const t = entrada.value.trim(); if (t) { entrada.value = ""; enviar(t, "voz"); } };
  r.start();
}

mic.addEventListener("click", () => {
  if (estado.ocupado) return toast("Espere la respuesta anterior");
  if (grabador?.state === "recording") return pararGrabacion();
  if (estado.sistema && !estado.sistema.stt) return dictadoNavegador();
  if (!window.MediaRecorder) return dictadoNavegador();
  empezarGrabacion();
});

async function hablar(texto) {
  callar();
  const limpio = texto.replace(/\[\d+\]/g, "").replace(/[*_#>`]/g, "");
  etapa("tts", "inicio");
  const t0 = performance.now();
  if (estado.sistema?.tts) {
    try {
      const r = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ texto: limpio }) });
      if (r.ok) {
        const url = URL.createObjectURL(await r.blob());
        reproductor = new Audio(url);
        asegurarAudio();
        const an = audioCtx.createAnalyser(); an.fftSize = 128;
        const src = audioCtx.createMediaElementSource(reproductor); src.connect(an); an.connect(audioCtx.destination);
        etapa("tts", "fin", Math.round(performance.now() - t0));
        mic.classList.add("hablando"); dibujar(an, "#2F5D50");
        reproductor.onended = () => { mic.classList.remove("hablando"); detenerDibujo(); URL.revokeObjectURL(url); };
        return reproductor.play();
      }
    } catch (_) { /* respaldo abajo */ }
  }
  if (!("speechSynthesis" in window)) return etapa("tts", "fin");
  const u = new SpeechSynthesisUtterance(limpio);
  const voces = speechSynthesis.getVoices();
  u.voice = voces.find((v) => v.lang === "es-CO") || voces.find((v) => v.lang.startsWith("es-US") || v.lang.startsWith("es-MX")) || voces.find((v) => v.lang.startsWith("es")) || null;
  u.lang = u.voice?.lang || "es-CO"; u.rate = 1.03;
  u.onstart = () => { etapa("tts", "fin", Math.round(performance.now() - t0)); $('.nodo[data-etapa="tts"] b').textContent = "Voz"; mic.classList.add("hablando"); dibujar(null, "#2F5D50"); };
  u.onend = () => { mic.classList.remove("hablando"); detenerDibujo(); };
  speechSynthesis.speak(u);
}
function callar() {
  if (reproductor) { reproductor.pause(); reproductor = null; }
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  mic.classList.remove("hablando");
  if (grabador?.state !== "recording") detenerDibujo();
}

/* =====================================================================
   Documentos
   ===================================================================== */
let plantilla = Plantillas[0];
const valores = {};
function pintarTipos() {
  $("#tipos-doc").innerHTML = Plantillas.map((p) => `<button class="tipo ${p.id === plantilla.id ? "activo" : ""}" data-id="${p.id}"><b>${esc(p.nombre)}</b><small>${esc(p.desc)}</small></button>`).join("");
  $$(".tipo").forEach((b) => b.addEventListener("click", () => { plantilla = Plantillas.find((p) => p.id === b.dataset.id); pintarTipos(); pintarForm(); }));
}
function pintarForm() {
  $("#form-doc").innerHTML = plantilla.campos.map((c) => {
    const val = esc(valores[c.id] ?? c.valor ?? "");
    const ctl = c.tipo === "area" ? `<textarea name="${c.id}" placeholder="${esc(c.ph)}">${val}</textarea>`
      : `<input name="${c.id}" type="${c.tipo === "date" ? "date" : "text"}" placeholder="${esc(c.ph)}" value="${val}">`;
    return `<label class="campo"><span>${esc(c.label)}</span>${ctl}</label>`;
  }).join("");
  $$("#form-doc [name]").forEach((el) => el.addEventListener("input", () => { valores[el.name] = el.value; pintarHoja(); }));
  pintarHoja();
}
function pintarHoja() {
  const v = {}; plantilla.campos.forEach((c) => (v[c.id] = valores[c.id] ?? c.valor ?? ""));
  $("#hoja").innerHTML = plantilla.render(v);
}
$("#btn-imprimir").addEventListener("click", () => window.print());
$("#btn-redactar").addEventListener("click", async () => {
  const hechos = valores.hechos?.trim();
  if (!hechos) return toast("Escriba primero los hechos con sus palabras");
  const b = $("#btn-redactar"); b.disabled = true; b.textContent = "Redactando…";
  try {
    const r = await api("/api/redactar", { method: "POST", body: JSON.stringify({ tipo: plantilla.nombre, hechos, campos: valores, conversacion_id: estado.conversacion }) });
    valores.hechos = r.hechos; pintarForm(); toast("Hechos redactados en lenguaje formal");
  } catch (e) { toast("No se pudo redactar: " + e.message); }
  finally { b.disabled = false; b.textContent = "✦ Redactar hechos con IA"; }
});
function desdeConversacion() {
  const mapa = { salud: "tutela", derechos_fundamentales: "peticion", consumidor: "garantia", deudas: "habeas", arrendamiento: "preaviso" };
  const id = mapa[estado.expediente?.area?.slug] || "peticion";
  plantilla = Plantillas.find((p) => p.id === id);
  valores.hechos = estado.ultimoUsuario.join("\n");
  pintarTipos(); pintarForm(); abrir("documentos");
  toast(`Plantilla sugerida: ${plantilla.nombre}`);
}
pintarTipos(); pintarForm();

/* =====================================================================
   Términos
   ===================================================================== */
let tramite = Terminos.TRAMITES[0];
const unidades = { habiles: "días hábiles", calendario: "días calendario", meses: "meses", anios: "años" };
$("#fecha-desde").value = Terminos.iso(new Date());
function pintarTramites() {
  $("#tramites").innerHTML = Terminos.TRAMITES.map((t) => `<button class="tramite ${t.id === tramite.id ? "activo" : ""}" data-id="${t.id}"><b>${esc(t.nombre)}</b><small>${esc(t.norma)}</small><em>${t.n} ${unidades[t.u]}</em></button>`).join("");
  $$(".tramite").forEach((b) => b.addEventListener("click", () => { tramite = Terminos.TRAMITES.find((t) => t.id === b.dataset.id); pintarTramites(); calcular(); }));
}
function calcular() {
  const desde = new Date($("#fecha-desde").value + "T12:00");
  if (isNaN(desde)) return;
  const { vence, contados } = Terminos.contar(desde, tramite.n, tramite.u);
  const fmt = (o) => vence.toLocaleDateString("es-CO", o);
  const restan = Math.ceil((vence - new Date().setHours(12, 0, 0, 0)) / 864e5);
  $("#hoja-calendario").innerHTML = `<div class="mes">${fmt({ month: "long" })} ${vence.getFullYear()}</div><div class="dia">${vence.getDate()}</div>
    <div class="semana">${fmt({ weekday: "long" })}</div>
    <div class="detalle"><b>${esc(tramite.nombre)}</b><br>${tramite.n} ${unidades[tramite.u]} · ${esc(tramite.norma)}<br>${restan > 0 ? `Faltan ${restan} días` : restan === 0 ? "Vence hoy" : `Venció hace ${-restan} días`}</div>`;
  const meses = [];
  if (tramite.u === "meses" || tramite.u === "anios") meses.push(new Date(desde.getFullYear(), desde.getMonth(), 1), new Date(vence.getFullYear(), vence.getMonth(), 1));
  else for (let d = new Date(desde.getFullYear(), desde.getMonth(), 1); d <= vence; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) meses.push(d);
  const isoIni = Terminos.iso(desde), isoFin = Terminos.iso(vence);
  $("#meses").innerHTML = meses.slice(0, 4).map((m) => {
    const dias = new Date(m.getFullYear(), m.getMonth() + 1, 0).getDate();
    const off = (m.getDay() + 6) % 7;
    let celdas = ["L", "M", "X", "J", "V", "S", "D"].map((d) => `<span class="cab">${d}</span>`).join("") + "<span></span>".repeat(off);
    for (let d = 1; d <= dias; d++) {
      const f = new Date(m.getFullYear(), m.getMonth(), d, 12), k = Terminos.iso(f), fest = Terminos.esFestivo(f);
      const cl = [f.getDay() % 6 === 0 ? "finde" : "", fest ? "festivo" : "", contados.has(k) ? "contado" : "", k === isoIni ? "inicio" : "", k === isoFin ? "fin" : ""].join(" ");
      celdas += `<span class="${cl}" title="${fest ? esc(fest) : ""}">${d}</span>`;
    }
    return `<div class="mes-cal"><h5>${m.toLocaleDateString("es-CO", { month: "long", year: "numeric" })}</h5><div class="grid">${celdas}</div></div>`;
  }).join("") + `<div class="leyenda"><span><i style="background:color-mix(in srgb,var(--salvia) 30%,transparent)"></i>día contado</span><span><i style="background:var(--lacre)"></i>vencimiento</span><span style="color:#c0392b">festivo</span><span><i style="outline:1.5px dashed var(--tinta)"></i>inicio</span></div>`;
}
$("#fecha-desde").addEventListener("input", calcular);
pintarTramites(); calcular();

/* =====================================================================
   Directorio
   ===================================================================== */
let areas = [], entidades = [], filtroArea = null;
alAbrir.directorio = async () => {
  if (!areas.length) { try { [areas, entidades] = await Promise.all([api("/api/areas"), api("/api/entidades")]); } catch (_) { return toast("No pude cargar el directorio"); } }
  $("#filtros-areas").innerHTML = `<button class="filtro ${!filtroArea ? "activo" : ""}" data-a="">Todas</button>` +
    areas.map((a) => `<button class="filtro ${filtroArea === a.slug ? "activo" : ""}" data-a="${a.slug}">${esc(a.simbolo)} ${esc(a.nombre)}</button>`).join("");
  $$(".filtro").forEach((b) => b.addEventListener("click", () => { filtroArea = b.dataset.a || null; alAbrir.directorio(); }));
  $("#directorio").innerHTML = entidades.filter((e) => !filtroArea || e.areas.includes(filtroArea)).map((e, i) => `
    <div class="entidad" style="animation-delay:${i * 30}ms"><small>${esc(e.tipo)} · ${esc(e.municipio)}</small><h4>${esc(e.nombre)}</h4>
    ${/^\d{3}$/.test(e.contacto) ? `<a class="tel" href="tel:${e.contacto}">${e.contacto}</a>` : `<span class="contacto">${esc(e.contacto)}</span>`}
    <p>${esc(e.nota || "")}</p><p class="nota">${esc(e.canal || "")}${e.gratuito ? " · gratuito" : ""}</p></div>`).join("");
};

/* =====================================================================
   Laboratorio
   ===================================================================== */
function dial(valor, etiqueta, sub) {
  const r = 38, c = 2 * Math.PI * r, v = Math.max(0, Math.min(1, valor));
  return `<div class="dial"><svg viewBox="0 0 96 96"><circle cx="48" cy="48" r="${r}" fill="none" stroke="var(--regla)" stroke-width="7"/>
    <circle cx="48" cy="48" r="${r}" fill="none" stroke="${v >= .8 ? "var(--salvia)" : v >= .6 ? "var(--laton)" : "var(--lacre)"}" stroke-width="7" stroke-linecap="round"
    stroke-dasharray="${c * v} ${c}" transform="rotate(-90 48 48)"/><text x="48" y="54" text-anchor="middle" font-family="JetBrains Mono" font-size="17" font-weight="600" fill="currentColor">${Math.round(v * 100)}%</text></svg>
    <b>${etiqueta}</b><small>${sub}</small></div>`;
}
function pintarEvaluacion(ev) {
  if (!ev?.resumen) return;
  const s = ev.resumen;
  $("#diales").innerHTML = dial(s.exactitud_area, "Área correcta", "clasificación") + dial(s.hit_3, "Hit@3", "fuente en top 3") +
    dial(s.hit_5, "Hit@5", "fuente en top 5") + dial(s.mrr, "MRR", "rango recíproco") + dial(s.emergencias, "Emergencias", "detección") +
    (s.cobertura_respuesta != null ? dial(s.cobertura_respuesta, "Cobertura", "claves en respuesta") : "") +
    `<div class="dial"><svg viewBox="0 0 96 96"><text x="48" y="56" text-anchor="middle" font-family="JetBrains Mono" font-size="20" font-weight="600" fill="currentColor">${s.latencia_ms}</text></svg><b>ms / caso</b><small>${s.casos} casos</small></div>`;
  $("#tabla-eval").innerHTML = `<table><thead><tr><th>#</th><th>Pregunta</th><th>Área esperada</th><th>Obtenida</th><th>Rango fuente</th><th>ms</th></tr></thead><tbody>${
    ev.casos.map((c, i) => `<tr><td>${i + 1}</td><td>${esc(c.pregunta)}</td><td><code>${c.area_esperada}</code></td>
      <td class="${c.area_esperada === c.area_obtenida ? "ok" : "mal"}">${c.area_esperada === c.area_obtenida ? "✓" : "✗"} <code>${c.area_obtenida}</code></td>
      <td class="${c.rango && c.rango <= 3 ? "ok" : "mal"}">${c.rango ?? "—"}</td><td><code>${c.ms}</code></td></tr>`).join("")}</tbody></table>`;
}
alAbrir.laboratorio = async () => {
  const s = estado.sistema;
  $("#arquitectura").innerHTML = [
    ["Entrada", "Voz / texto", "MediaRecorder · WebM"],
    ["STT", "faster-whisper", `${s?.whisper || "small"} · int8 · CPU`],
    ["Embedding", "EmbeddingGemma", "768 dim · Ollama"],
    ["Recuperación", "PostgreSQL + pgvector", "HNSW coseno + tsvector · RRF"],
    ["Razonamiento", s?.llm?.modelo || "LLM", s?.llm?.proveedor === "openai" ? "API compatible OpenAI" : "Ollama · CPU"],
    ["Salida", "Piper TTS", "es_MX · ONNX · CPU"],
  ].map(([a, b, c]) => `<div class="arq"><small>${a}</small><b>${esc(b)}</b><p>${esc(c)}</p></div>`).join("");
  try {
    const [m, ev, docs] = await Promise.all([api("/api/metricas"), api("/api/evaluacion"), api("/api/documentos-fuente")]);
    const l = m.latencias || {};
    const etapas = [["STT (Whisper)", l.stt], ["Embedding", l.embedding], ["pgvector", l.pgvector], ["Primer token", l.primer_token], ["LLM completo", l.llm]];
    const max = Math.max(1, ...etapas.map(([, v]) => +v || 0));
    $("#lab-latencias").innerHTML = etapas.map(([n, v]) => `<div class="fila"><span>${n}</span><div class="pista"><span style="width:${((+v || 0) / max) * 100}%"></span></div><small>${v == null ? "—" : v + " ms"}</small></div>`).join("") +
      `<p class="nota">${l.respuestas || 0} respuestas · ${m.documentos_generados} documentos generados · ${m.canales.map((c) => `${c.n} por ${c.canal}`).join(", ") || "sin consultas"}</p>`;
    const maxA = Math.max(1, ...m.por_area.map((a) => a.n));
    $("#lab-areas").innerHTML = m.por_area.map((a) => `<div class="fila"><span>${esc(a.simbolo)} ${esc(a.nombre)}</span><div class="pista"><span style="width:${(a.n / maxA) * 100}%;background:${a.color}"></span></div><small>${a.n}</small></div>`).join("");
    pintarEvaluacion(ev);
    $("#lab-docs").innerHTML = docs.map((d) => `<a href="${esc(d.url || "#")}" target="_blank" rel="noopener"><b>${esc(d.titulo)}</b><small>${esc(d.fuente)}</small><span>${d.fragmentos} fragmentos vectorizados</span></a>`).join("");
  } catch (_) { toast("No pude cargar las métricas"); }
};
$("#btn-evaluar").addEventListener("click", async () => {
  const b = $("#btn-evaluar"); b.disabled = true; b.textContent = "Evaluando…";
  try { pintarEvaluacion(await api(`/api/evaluacion?con_llm=${$("#eval-llm").checked}`, { method: "POST" })); toast("Evaluación completada y guardada en PostgreSQL"); }
  catch (e) { toast("Error en la evaluación: " + e.message); }
  finally { b.disabled = false; b.textContent = "Ejecutar evaluación"; }
});

/* =====================================================================
   Archivo (historial)
   ===================================================================== */
alAbrir.archivo = async () => {
  try {
    const lista = await api("/api/conversaciones");
    $("#archivo").innerHTML = `<button class="carpeta" id="nueva" style="--c:var(--lacre)"><small>Nueva</small><h4>＋ Abrir un expediente nuevo</h4></button>` +
      lista.map((c) => `<div class="carpeta" data-id="${c.id}" style="--c:${c.color || "var(--tinta-3)"}" role="button" tabindex="0">
        <button class="borrar" data-borrar="${c.id}" title="Eliminar">×</button>
        <small>${numeroExpediente(c.id)} · ${new Date(c.actualizada).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" })}</small>
        <h4>${esc(c.titulo || "Sin título")}</h4><span class="area">${esc(c.simbolo || "")} ${esc(c.area || "Sin área")}</span>
        <span class="nota"> · ${c.mensajes} mensajes · urgencia ${esc(c.urgencia || "—")}</span></div>`).join("");
    $("#nueva").addEventListener("click", () => { limpiarConsulta(); abrir("consulta"); });
    $$(".carpeta[data-id]").forEach((el) => el.addEventListener("click", async (e) => {
      if (e.target.dataset.borrar) {
        e.stopPropagation();
        await api(`/api/conversaciones/${e.target.dataset.borrar}`, { method: "DELETE" });
        if (estado.conversacion === e.target.dataset.borrar) limpiarConsulta();
        return alAbrir.archivo();
      }
      cargarConversacion(el.dataset.id);
    }));
  } catch (_) { toast("No pude cargar el archivo"); }
};

async function cargarConversacion(id) {
  const msgs = await api(`/api/conversaciones/${id}`);
  limpiarConsulta(); estado.conversacion = id; $("#exp-num").textContent = numeroExpediente(id);
  abrir("consulta");
  for (const m of msgs) {
    if (m.rol === "usuario") { agregarUsuario(m.contenido, m.canal); estado.ultimoUsuario.push(m.contenido); }
    else {
      const n = nuevoFolio(); const c = $(".folio__cuerpo", n);
      c.innerHTML = md(m.contenido); enlazarCitas(c); pieFolio(n, m.contenido);
      if (m.expediente) pintarExpediente(m.expediente);
      if (m.fuentes) pintarFuentes(m.fuentes);
      if (m.metricas) pintarMetricas(m.metricas);
    }
  }
}

/* ---------- Arranque ---------- */
cargarEstado();
setInterval(cargarEstado, 30000);
if ("speechSynthesis" in window) speechSynthesis.getVoices();
