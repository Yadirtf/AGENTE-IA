/* =====================================================================
   AMPARO — Llamada en vivo
   Turnos por voz con detección de habla, respuesta por frases e interrupción.

   Cómo funciona (todo pensado para CPU):
   1. El micrófono se analiza 20 veces por segundo. Un umbral que se adapta al
      ruido del cuarto decide cuándo empieza y cuándo termina la persona de hablar.
      Se guardan ~350 ms previos para no cortar la primera sílaba.
   2. Al callar ~0,85 s, el audio se envía como WAV a Whisper (modelo rápido).
   3. /api/llamada responde por frases (SSE). Cada frase se convierte en voz apenas
      llega, mientras el LLM sigue escribiendo la siguiente.
   4. Si la persona habla mientras Amparo habla o piensa, se corta todo al instante
      (audio, voz y petición) y Amparo escucha.
   ===================================================================== */
(() => {
  const L = {
    activa: false, fase: "inactiva", cid: null, ctx: null, flujo: null, proc: null, anEntrada: null, anSalida: null,
    tasa: 48000, ruido: 0.008, vozDesde: null, silencioDesde: null, grabando: false, pcm: [], previo: [],
    abort: null, cola: [], sonando: null, turno: 0, llmTermino: true, inicio: 0, reloj: null, silenciado: false,
    rellenos: [], cadenaTTS: Promise.resolve(), turnos: 0, interrupciones: 0, colgarAlTerminar: null,
    reconocedor: null, burbuja: null, frasesTurno: 0, ultimas: [], ultimaBurbuja: null,
  };
  const FASES = {
    inactiva: "Lista para conversar", conectando: "Conectando…", escuchando: "Le escucho…", usuario: "Hablando usted…",
    transcribiendo: "Entendiendo lo que dijo…", pensando: "Pensando…", hablando: "Amparo está hablando", terminada: "Llamada terminada",
  };
  const RELLENOS = [
    { emocion: "calida", texto: "Mmm, a ver…" }, { emocion: "tranquila", texto: "Claro, déjeme revisar." },
    { emocion: "calida", texto: "Entiendo, un momentico." }, { emocion: "animada", texto: "Ajá, ya le cuento." },
  ];
  const $l = (s) => document.querySelector(s);
  const ahora = () => performance.now();
  const usaPiper = () => estado.sistema?.tts && !estado.vozId.startsWith("nav:");

  /* ---------- Estado visual ---------- */
  function fase(f) {
    L.fase = f;
    $l("#vista-llamada .llamada").dataset.fase = f;
    $l("#llamada-estado").textContent = L.silenciado && L.activa ? "Micrófono silenciado" : FASES[f];
  }
  function relojTick() {
    const s = Math.floor((Date.now() - L.inicio) / 1000);
    $l("#llamada-reloj").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }

  /* ---------- Orbe animado ---------- */
  const lienzo = $l("#orbe-lienzo"), g = lienzo.getContext("2d");
  const datos = new Uint8Array(64);
  let nivelSuave = 0, animOrbe = null;
  function nivel(an) {
    if (!an) return 0;
    an.getByteFrequencyData(datos);
    return datos.reduce((a, b) => a + b, 0) / datos.length / 255;
  }
  function dibujarOrbe() {
    const W = lienzo.width, c = W / 2, t = ahora() / 1000;
    const css = getComputedStyle(document.documentElement);
    const color = { usuario: css.getPropertyValue("--lacre"), pensando: css.getPropertyValue("--laton"),
      transcribiendo: css.getPropertyValue("--laton") }[L.fase]?.trim() || css.getPropertyValue("--salvia").trim();
    const n = L.fase === "hablando" ? nivel(L.anSalida) * 1.6 : L.fase === "usuario" || L.fase === "escuchando" ? nivel(L.anEntrada) * 1.8 : 0;
    nivelSuave += (Math.min(1, n) - nivelSuave) * 0.25;
    g.clearRect(0, 0, W, W);
    const base = W * 0.26;
    for (let anillo = 3; anillo >= 1; anillo--) {           // halos que respiran
      const r = base + anillo * 18 + nivelSuave * 46 * anillo + Math.sin(t * 1.6 + anillo) * 3;
      g.beginPath(); g.arc(c, c, r, 0, Math.PI * 2);
      g.fillStyle = color; g.globalAlpha = 0.06 + nivelSuave * 0.05; g.fill();
    }
    g.globalAlpha = 1;
    g.lineWidth = 3; g.strokeStyle = color; g.lineCap = "round";
    if (L.fase === "pensando" || L.fase === "transcribiendo" || L.fase === "conectando") {
      const a = t * 3.2;                                     // arco que gira mientras piensa
      g.beginPath(); g.arc(c, c, base + 8, a, a + Math.PI * 0.6); g.stroke();
      g.beginPath(); g.arc(c, c, base + 8, a + Math.PI, a + Math.PI * 1.6); g.stroke();
    } else if (L.activa) {
      const puntos = 72;                                    // onda circular con la voz
      g.beginPath();
      for (let i = 0; i <= puntos; i++) {
        const ang = (i / puntos) * Math.PI * 2;
        const v = datos[i % 64] / 255;
        const r = base + 6 + (L.fase === "escuchando" ? Math.sin(t * 2 + i * 0.3) * 2 : v * 30 * (0.4 + nivelSuave));
        const x = c + Math.cos(ang) * r, y = c + Math.sin(ang) * r;
        i ? g.lineTo(x, y) : g.moveTo(x, y);
      }
      g.closePath(); g.stroke();
    }
    $l("#orbe").style.setProperty("--escala", (1 + nivelSuave * 0.08).toFixed(3));
    animOrbe = requestAnimationFrame(dibujarOrbe);
  }

  /* ---------- Subtítulos ---------- */
  const subs = $l("#ll-subtitulos");
  function bajarSubs() { subs.scrollTop = subs.scrollHeight; }
  function burbujaUsuario(texto, ms) {
    subs.querySelector(".nota")?.remove();
    const d = document.createElement("div");
    d.className = "sub sub--usuario";
    d.innerHTML = `<small>Usted${ms ? ` · Whisper ${ms} ms` : ""}</small><p>${esc(texto)}</p>`;
    subs.appendChild(d); bajarSubs();
    return d;
  }
  function burbujaAmparo() {
    subs.querySelector(".nota")?.remove();
    const d = document.createElement("div");
    d.className = "sub sub--amparo";
    d.innerHTML = `<small>Amparo</small><p></p><div class="sub__fuentes"></div>`;
    subs.appendChild(d); bajarSubs();
    return d;
  }
  function agregarFraseSub(frase, relleno = false) {
    if (!L.burbuja) L.burbuja = burbujaAmparo();
    const s = document.createElement("span");
    s.textContent = frase.texto + " "; s.dataset.e = frase.emocion;
    s.classList.add("pendiente");                       // se ve tenue hasta que Amparo la dice
    if (relleno) s.classList.add("relleno");
    $(".sub__p, p", L.burbuja).appendChild(s); bajarSubs();
    return s;
  }

  /* ---------- Voz de Amparo: cola de frases ---------- */
  function sintetizar(frase) {
    if (!usaPiper()) return Promise.resolve(null);
    // En serie: la CPU sintetiza una frase a la vez mientras suena la anterior.
    const p = L.cadenaTTS.then(() => fetch("/api/tts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ segmentos: [frase], voz: estado.vozId.startsWith("piper:") ? estado.vozId.slice(6) : null, velocidad: estado.velocidad }),
    }).then((r) => (r.ok ? r.blob() : null)).catch(() => null));
    L.cadenaTTS = p.catch(() => null);
    return p;
  }
  function encolar(frase, opciones = {}) {
    const span = opciones.span || agregarFraseSub(frase, opciones.relleno);
    L.cola.push({ frase, span, turno: L.turno, audio: opciones.audio ?? sintetizar(frase), relleno: opciones.relleno });
    reproducir();
  }
  async function reproducir() {
    if (L.sonando || !L.cola.length) return;
    const item = L.cola.shift();
    if (item.turno !== L.turno) return reproducir();
    L.sonando = item;
    const blob = await item.audio;
    if (L.sonando !== item || item.turno !== L.turno) return;
    fase("hablando");
    item.span.classList.remove("pendiente");
    item.span.classList.add("dicha");
    const fin = () => {
      item.span.classList.remove("dicha");
      if (L.sonando !== item) return;
      L.sonando = null;
      if (L.cola.length) return reproducir();
      if (L.llmTermino) {
        if (L.colgarAlTerminar) return colgar(L.colgarAlTerminar);
        fase("escuchando");
      } else fase("pensando");
    };
    if (blob) {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      item.elemento = audio;
      try { L.ctx.createMediaElementSource(audio).connect(L.anSalida); } catch (_) {}
      audio.onended = () => { URL.revokeObjectURL(url); fin(); };
      audio.onerror = fin;
      audio.play().catch(fin);
    } else if ("speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(limpiarVoz(item.frase.texto));
      const voz = vozNavegador(estado.vozId.startsWith("nav:") ? estado.vozId.slice(4) : null);
      const [ritmo, tono] = PROSODIA_NAV[item.frase.emocion] || [1, 1];
      u.voice = voz; u.lang = voz?.lang || "es-CO"; u.rate = ritmo * estado.velocidad; u.pitch = tono;
      // Algunos navegadores no disparan onend: un tope por duración estimada evita que la cola se trabe.
      const tope = setTimeout(fin, 1800 + item.frase.texto.length * 85 / estado.velocidad);
      u.onend = u.onerror = () => { clearTimeout(tope); fin(); };
      speechSynthesis.speak(u);
    } else fin();
  }
  function callarAmparo() {
    L.cola = [];
    if (L.sonando?.elemento) { L.sonando.elemento.pause(); }
    L.sonando?.span?.classList.remove("dicha");
    L.sonando = null;
    if ("speechSynthesis" in window) speechSynthesis.cancel();
  }

  /* ---------- Interrupción ---------- */
  function interrumpir() {
    const habia = L.sonando || L.cola.length || !L.llmTermino;
    L.turno++;
    L.abort?.abort(); L.abort = null;
    L.llmTermino = true;
    callarAmparo();
    if (habia && L.burbuja) {
      L.interrupciones++;
      L.burbuja.querySelectorAll("span.pendiente").forEach((x) => x.remove());   // lo que no alcanzó a decir
      const p = L.burbuja.querySelector("p");
      if (p && !p.textContent.trim()) p.textContent = "…";
      else p?.insertAdjacentText("beforeend", "…");
      L.burbuja.classList.add("interrumpida");
      L.burbuja.querySelector("small").textContent = "Amparo · usted la interrumpió";
    }
    L.burbuja = null;
  }

  /* ---------- Micrófono y detección de habla ---------- */
  function rms(buf) { let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i]; return Math.sqrt(s / buf.length); }
  function procesarCuadro(e) {
    if (!L.activa || L.silenciado) return;
    const d = e.inputBuffer.getChannelData(0);
    const cuadro = new Float32Array(d);
    const r = rms(cuadro), t = ahora();
    const amparoSuena = !!L.sonando;
    // Mientras Amparo habla se exige más energía, para que su propia voz no la interrumpa.
    const umbral = amparoSuena ? Math.max(L.ruido * 7, 0.045) : Math.max(L.ruido * 3.2, 0.016);
    L.previo.push(cuadro); if (L.previo.length > 8) L.previo.shift();
    if (!L.grabando) {
      if (r > umbral) {
        L.vozDesde ??= t;
        if (t - L.vozDesde > (amparoSuena ? 240 : 150)) empezarTurno();
      } else {
        L.vozDesde = null;
        if (!amparoSuena && r < 0.05) L.ruido = L.ruido * 0.97 + r * 0.03;   // se adapta al ruido del cuarto
      }
      return;
    }
    L.pcm.push(cuadro);
    if (r > Math.max(L.ruido * 2.2, 0.011)) L.silencioDesde = null;
    else L.silencioDesde ??= t;
    const dur = L.pcm.length * cuadro.length / L.tasa;
    if ((L.silencioDesde && t - L.silencioDesde > 850) || dur > 25) terminarTurno();
  }
  function empezarTurno() {
    // Si solo hizo una pausa (Amparo aún no ha dicho nada de su respuesta), se une con lo anterior.
    const continua = !L.frasesTurno && L.turno > 0 &&
      (L.fase === "transcribiendo" || L.fase === "pensando" || (L.fase === "hablando" && L.sonando?.relleno));
    if (L.fase !== "escuchando") interrumpir();         // barge-in: hablaba, pensaba o transcribía
    L.grabando = true; L.silencioDesde = null; L.vozDesde = null;
    L.pcm = continua ? [...L.ultimas, ...L.previo] : [...L.previo];
    if (continua) L.ultimaBurbuja?.remove();
    fase("usuario");
  }
  function terminarTurno() {
    L.grabando = false;
    const muestras = L.pcm; L.pcm = [];
    L.ultimas = muestras;
    const segundos = muestras.reduce((a, b) => a + b.length, 0) / L.tasa;
    if (segundos < 0.45) { fase("escuchando"); return; }          // tos o ruido corto
    procesarTurno(wav(muestras, L.tasa));
  }
  function wav(cuadros, tasa, destino = 16000) {
    const total = cuadros.reduce((a, b) => a + b.length, 0);
    const todo = new Float32Array(total); let o = 0;
    for (const c of cuadros) { todo.set(c, o); o += c.length; }
    const paso = tasa / destino, n = Math.floor(total / paso);
    const buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
    const txt = (p, s) => [...s].forEach((ch, i) => v.setUint8(p + i, ch.charCodeAt(0)));
    txt(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); txt(8, "WAVE"); txt(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, destino, true);
    v.setUint32(28, destino * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); txt(36, "data"); v.setUint32(40, n * 2, true);
    for (let i = 0; i < n; i++) {
      const a = Math.floor(i * paso), b = Math.min(total, Math.floor((i + 1) * paso));
      let s = 0; for (let j = a; j < b; j++) s += todo[j];
      const x = Math.max(-1, Math.min(1, s / Math.max(1, b - a)));
      v.setInt16(44 + i * 2, x * 32767, true);
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  /* ---------- Un turno: STT → LLM por frases → voz ---------- */
  async function procesarTurno(audio) {
    const turno = ++L.turno;
    L.burbuja = null; L.ultimaBurbuja = null;
    fase("transcribiendo");
    const relleno = setTimeout(() => {                 // como una persona: "Mmm, a ver…"
      if (turno === L.turno && !L.frasesTurno && !L.sonando) {
        const r = L.rellenos[Math.floor(Math.random() * L.rellenos.length)];
        if (r) encolar(r.frase, { audio: Promise.resolve(r.blob), relleno: true });
      }
    }, 900);
    L.frasesTurno = 0;
    let texto = "", msStt = null;
    try {
      const fd = new FormData(); fd.append("audio", audio, "turno.wav");
      const t0 = ahora();
      const r = await fetch("/api/stt?rapido=true", { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      const j = await r.json(); texto = (j.texto || "").trim(); msStt = j.ms ?? Math.round(ahora() - t0);
    } catch (e) {
      clearTimeout(relleno);
      if (turno === L.turno) { toast("No pude transcribir: " + e.message); fase("escuchando"); }
      return;
    }
    if (turno !== L.turno) return clearTimeout(relleno);
    if (!texto || texto.length < 2) { clearTimeout(relleno); callarAmparo(); fase("escuchando"); return; }
    L.ultimaBurbuja = burbujaUsuario(texto, msStt);
    await conversar(texto, turno, msStt);
    clearTimeout(relleno);
  }
  async function conversar(texto, turno, msStt) {
    L.turnos++;
    fase("pensando");
    L.llmTermino = false;
    L.abort = new AbortController();
    const t0 = ahora();
    try {
      const resp = await fetch("/api/llamada", {
        method: "POST", headers: { "Content-Type": "application/json" }, signal: L.abort.signal,
        body: JSON.stringify({ texto, conversacion_id: L.cid, alias: estado.alias || null, ms_stt: msStt }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      for await (const { tipo, datos } of eventos(resp)) {
        if (turno !== L.turno) return;
        if (tipo === "conversacion") L.cid = datos.id;
        else if (tipo === "frase") {
          if (!L.frasesTurno) $l("#ll-metricas").textContent = `Whisper ${msStt ?? "—"} ms · primera frase ${Math.round(ahora() - t0)} ms`;
          L.frasesTurno++;
          encolar(datos);
        } else if (tipo === "fuentes") pintarFuentes(datos);
        else if (tipo === "emergencia") mostrarEmergencia(datos);
        else if (tipo === "agenda") pintarAgenda(datos);
        else if (tipo === "cita") pintarCita(datos);
        else if (tipo === "colgar") L.colgarAlTerminar = datos.motivo;
        else if (tipo === "error") throw new Error(datos.mensaje);
      }
    } catch (e) {
      if (e.name === "AbortError" || turno !== L.turno) return;
      toast(e.message.slice(0, 160));
      encolar({ emocion: "calida", texto: "Uy, tuve un problema para responderle. ¿Me lo repite, por favor?" });
    } finally {
      if (turno === L.turno) {
        L.llmTermino = true; L.abort = null;
        if (!L.sonando && !L.cola.length) {
          if (L.colgarAlTerminar) colgar(L.colgarAlTerminar); else fase("escuchando");
        }
      }
    }
  }
  /* ---------- Agenda por voz: la ficha de la cita se llena mientras se habla ---------- */
  const CAMPOS_AGENDA = [
    ["entidad", "Lugar"], ["fecha", "Día"], ["hora", "Hora"], ["modalidad", "Modalidad"],
    ["nombre", "A nombre de"], ["telefono", "Celular"], ["documento", "Cédula"], ["autorizacion", "Datos (Ley 1581)"],
  ];
  const MODOS = { presencial: "Presencial", virtual: "Virtual", telefonica: "Por teléfono" };
  const fechaLarga = (iso) => new Date(iso + "T12:00").toLocaleDateString("es-CO", { weekday: "long", day: "numeric", month: "long" });
  const horaLarga = (h) => { const n = +h.slice(0, 2); return `${n > 12 ? n - 12 : n}:${h.slice(3)} ${n < 12 ? "a. m." : "p. m."}`; };
  function valorAgenda(k, v) {
    if (v === null || v === undefined || v === "") return "";
    if (k === "fecha") return fechaLarga(v);
    if (k === "hora") return horaLarga(v);
    if (k === "modalidad") return MODOS[v] || v;
    if (k === "telefono") return v.replace(/(\d{3})(\d{3})(\d+)/, "$1 $2 $3");
    if (k === "autorizacion") return v ? "Autorizado" : "";
    return v;
  }
  function pintarAgenda(a) {
    const caja = $l("#ll-agenda");
    if (!a) { caja.hidden = true; caja.innerHTML = ""; return; }
    const pasoCampo = a.paso === "corregir" || a.paso === "confirmar" ? null : a.paso;
    caja.hidden = false;
    caja.className = "ll-agenda";
    caja.innerHTML = `<div class="ll-agenda__cab"><span class="sobretitulo">Agendando su cita</span>
        <small>${a.paso === "confirmar" ? "Esperando su confirmación" : a.paso === "corregir" ? "Corrigiendo" : "Paso a paso, por voz"}</small></div>
      <dl>${CAMPOS_AGENDA.map(([k, et]) => {
        const v = valorAgenda(k, a[k]);
        return `<div class="${v ? "listo" : ""} ${k === pasoCampo ? "actual" : ""}"><dt>${et}</dt><dd>${v ? esc(v) : k === pasoCampo ? "…escuchando" : "—"}</dd></div>`;
      }).join("")}</dl>`;
  }
  function pintarCita(c) {
    const caja = $l("#ll-agenda");
    caja.hidden = false;
    caja.className = "ll-agenda ll-agenda--lista";
    caja.innerHTML = `<div class="ll-agenda__sello">AGENDADA</div>
      <span class="sobretitulo">Constancia de cita Nº ${String(c.id).padStart(5, "0")}</span>
      <b class="ll-agenda__lugar">${esc(c.entidad?.nombre || "")}</b>
      <p class="ll-agenda__cuando">${esc(fechaLarga(c.fecha))} · ${esc(horaLarga(c.hora))} · ${esc(MODOS[c.modalidad] || c.modalidad)}</p>
      <p class="nota">A nombre de ${esc(c.consultante || "")}${c.entidad?.horario ? ` · Horario: ${esc(c.entidad.horario)}` : ""}</p>
      <button class="btn btn--chico" type="button">Ver constancia</button>`;
    $("button", caja).onclick = () => {
      estado.conversacion = L.cid;
      constancia(c, { nombre: c.consultante, documento: c.documento || "", motivo: c.motivo });
      $l("#dlg-cita").showModal();
    };
    toast("Cita agendada por voz · el caso pasó a «Remitido al consultorio»");
  }

  function pintarFuentes(lista) {
    if (!L.burbuja) L.burbuja = burbujaAmparo();
    $(".sub__fuentes", L.burbuja).innerHTML = lista.map((f) => `<span title="${esc(f.seccion)}">📚 ${esc(f.fuente || f.titulo)}</span>`).join("");
  }

  /* ---------- Respaldo: reconocimiento de voz del navegador ---------- */
  function reconocimientoNavegador() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return false;
    const r = new SR(); r.lang = "es-CO"; r.continuous = true; r.interimResults = true;
    r.onresult = (e) => {
      const res = e.results[e.results.length - 1];
      if (!res.isFinal) { if (L.fase !== "usuario" && res[0].transcript.trim().split(" ").length >= 2) { interrumpir(); fase("usuario"); } return; }
      const texto = res[0].transcript.trim();
      if (!texto) return;
      interrumpir();
      const turno = ++L.turno;
      burbujaUsuario(texto, null);
      conversar(texto, turno, null);
    };
    r.onend = () => { if (L.activa) try { r.start(); } catch (_) {} };
    r.start();
    L.reconocedor = r;
    return true;
  }

  /* ---------- Llamar y colgar ---------- */
  async function prepararRellenos() {
    L.rellenos = RELLENOS.map((frase) => ({ frase, blob: null }));
    if (!usaPiper()) return;
    for (const r of L.rellenos) { r.blob = await sintetizar(r.frase); if (!L.activa) return; }
  }
  async function llamar() {
    if (estado.cerradaDura) return toast("Esta sesión se cerró. Recargue la página para empezar de nuevo.");
    callar();
    fase("conectando");
    $l("#ll-resumen").hidden = true;
    try {
      L.flujo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (_) { fase("inactiva"); return toast("Necesito permiso para usar el micrófono"); }
    L.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (L.ctx.state === "suspended") await L.ctx.resume();
    L.tasa = L.ctx.sampleRate;
    const fuente = L.ctx.createMediaStreamSource(L.flujo);
    L.anEntrada = L.ctx.createAnalyser(); L.anEntrada.fftSize = 128; fuente.connect(L.anEntrada);
    L.anSalida = L.ctx.createAnalyser(); L.anSalida.fftSize = 128; L.anSalida.connect(L.ctx.destination);
    Object.assign(L, { activa: true, cid: null, turno: 0, turnos: 0, interrupciones: 0, colgarAlTerminar: null, llmTermino: true,
      silenciado: false, grabando: false, ruido: 0.008, burbuja: null, inicio: Date.now() });
    subs.innerHTML = "";
    $l("#ll-metricas").textContent = "";
    pintarAgenda(null);
    const conWhisper = estado.sistema?.stt !== false;
    if (conWhisper) {
      L.proc = L.ctx.createScriptProcessor(2048, 1, 1);
      L.proc.onaudioprocess = procesarCuadro;
      fuente.connect(L.proc);
      const mudo = L.ctx.createGain(); mudo.gain.value = 0;       // el procesador necesita una salida
      L.proc.connect(mudo); mudo.connect(L.ctx.destination);
    } else if (!reconocimientoNavegador()) {
      colgar(); return toast("Este navegador no permite la llamada sin Whisper en el servidor");
    }
    $l("#ll-llamar").hidden = true; $l("#ll-colgar").hidden = false; $l("#ll-silenciar").hidden = false;
    $l("#ll-silenciar").classList.remove("activo");
    L.reloj = setInterval(relojTick, 500); relojTick();
    document.body.classList.add("en-llamada");
    const n = estado.alias ? `, ${estado.alias}` : "";
    encolar({ emocion: "alegre", texto: `¡Hola${n}! Habla Amparo.` });
    encolar({ emocion: "calida", texto: "Cuénteme con calma, ¿en qué le puedo ayudar hoy?" });
    prepararRellenos();
  }
  function colgar(motivo) {
    if (!L.activa) return;
    interrumpir();
    L.activa = false;
    L.proc?.disconnect(); L.proc = null;
    L.reconocedor?.stop(); L.reconocedor = null;
    L.flujo?.getTracks().forEach((t) => t.stop());
    L.ctx?.close(); L.ctx = null;
    clearInterval(L.reloj);
    document.body.classList.remove("en-llamada");
    $l("#ll-llamar").hidden = false; $l("#ll-colgar").hidden = true; $l("#ll-silenciar").hidden = true;
    fase("terminada");
    const res = $l("#ll-resumen");
    res.hidden = false;
    res.innerHTML = `<b>${motivo ? esc(motivo) : "Gracias por llamar."}</b>
      <span>Duración ${$l("#llamada-reloj").textContent} · ${L.turnos} turnos · ${L.interrupciones} interrupciones</span>
      ${L.cid ? `<div><button class="btn btn--chico" type="button" data-a="ver">Ver la conversación</button>
      <button class="btn btn--sello btn--chico" type="button" data-a="cita">📅 Agendar cita gratuita</button></div>` : ""}`;
    res.onclick = (e) => {
      const a = e.target.dataset.a;
      if (a === "ver") cargarConversacion(L.cid);
      if (a === "cita") { estado.conversacion = L.cid; abrirCita([]); }
    };
    if (motivo) { estado.cerradaDura = true; cerrarSesion(motivo); }
  }

  $l("#ll-llamar").addEventListener("click", llamar);
  $l("#ll-colgar").addEventListener("click", () => colgar());
  $l("#ll-silenciar").addEventListener("click", () => {
    L.silenciado = !L.silenciado;
    if (L.silenciado && L.grabando) { L.grabando = false; L.pcm = []; }
    $l("#ll-silenciar").classList.toggle("activo", L.silenciado);
    $l("#ll-silenciar small").textContent = L.silenciado ? "Activar mic" : "Silenciar";
    fase(L.fase);
  });
  $l("#ll-voz").addEventListener("click", () => abrirVoces());
  document.addEventListener("keydown", (e) => {                     // Espacio: interrumpir a mano
    if (e.code === "Space" && L.activa && L.sonando && document.activeElement === document.body) { e.preventDefault(); interrumpir(); fase("escuchando"); }
  });
  window.addEventListener("beforeunload", () => colgar());
  fase("inactiva");
  dibujarOrbe();
  window.Llamada = { L, colgar, interrumpir, conversar };          // útil para depurar en la consola
})();
