/* Calendario judicial colombiano: festivos (Ley 51 de 1983) y conteo de términos. */
(function () {
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const sumar = (d, n) => { const r = new Date(d); r.setDate(r.getDate() + n); return r; };

  function pascua(anio) { // algoritmo de Butcher
    const a = anio % 19, b = Math.floor(anio / 100), c = anio % 100, d = Math.floor(b / 4), e = b % 4;
    const f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30;
    const i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
    const mes = Math.floor((h + l - 7 * m + 114) / 31), dia = ((h + l - 7 * m + 114) % 31) + 1;
    return new Date(anio, mes - 1, dia);
  }
  const lunesSiguiente = (d) => { const dow = d.getDay(); return dow === 1 ? d : sumar(d, (8 - dow) % 7); };

  const cache = {};
  function festivos(anio) {
    if (cache[anio]) return cache[anio];
    const f = new Map();
    const fijo = (m, d, n) => f.set(iso(new Date(anio, m - 1, d)), n);
    const movil = (m, d, n) => f.set(iso(lunesSiguiente(new Date(anio, m - 1, d))), n);
    fijo(1, 1, "Año Nuevo"); fijo(5, 1, "Día del Trabajo"); fijo(7, 20, "Independencia");
    fijo(8, 7, "Batalla de Boyacá"); fijo(12, 8, "Inmaculada Concepción"); fijo(12, 25, "Navidad");
    movil(1, 6, "Reyes Magos"); movil(3, 19, "San José"); movil(6, 29, "San Pedro y San Pablo");
    movil(8, 15, "Asunción"); movil(10, 12, "Día de la Raza"); movil(11, 1, "Todos los Santos");
    movil(11, 11, "Independencia de Cartagena");
    const p = pascua(anio);
    f.set(iso(sumar(p, -3)), "Jueves Santo"); f.set(iso(sumar(p, -2)), "Viernes Santo");
    f.set(iso(sumar(p, 43)), "Ascensión del Señor"); f.set(iso(sumar(p, 64)), "Corpus Christi");
    f.set(iso(sumar(p, 71)), "Sagrado Corazón");
    return (cache[anio] = f);
  }
  const esFestivo = (d) => festivos(d.getFullYear()).get(iso(d));
  const esHabil = (d) => d.getDay() !== 0 && d.getDay() !== 6 && !esFestivo(d);

  /** Cuenta un término desde `desde` (el día de inicio no se cuenta). */
  function contar(desde, cantidad, unidad) {
    const contados = [];
    let d = new Date(desde);
    if (unidad === "habiles") {
      let n = 0;
      while (n < cantidad) { d = sumar(d, 1); if (esHabil(d)) { n++; contados.push(iso(d)); } }
    } else if (unidad === "calendario") {
      for (let n = 0; n < cantidad; n++) { d = sumar(d, 1); contados.push(iso(d)); }
    } else if (unidad === "meses" || unidad === "anios") {
      const meses = unidad === "meses" ? cantidad : cantidad * 12;
      d = new Date(d.getFullYear(), d.getMonth() + meses, d.getDate());
    }
    return { vence: d, contados: new Set(contados) };
  }

  const TRAMITES = [
    { id: "peticion", nombre: "Respuesta a derecho de petición", norma: "Ley 1755/2015", n: 15, u: "habiles" },
    { id: "documentos", nombre: "Petición de documentos o información", norma: "Ley 1755/2015", n: 10, u: "habiles" },
    { id: "consulta", nombre: "Consulta a una autoridad", norma: "Ley 1755/2015", n: 30, u: "habiles" },
    { id: "tutela", nombre: "Fallo de la acción de tutela", norma: "Decreto 2591/1991", n: 10, u: "habiles" },
    { id: "impugnacion", nombre: "Impugnar el fallo de tutela", norma: "Decreto 2591/1991", n: 3, u: "habiles" },
    { id: "retracto", nombre: "Derecho de retracto (compra a distancia)", norma: "Ley 1480/2011", n: 5, u: "habiles" },
    { id: "reversion", nombre: "Solicitar reversión del pago", norma: "Ley 1480/2011", n: 5, u: "habiles" },
    { id: "proveedor", nombre: "Respuesta del proveedor a un reclamo", norma: "Ley 1480/2011", n: 15, u: "habiles" },
    { id: "servicios", nombre: "Respuesta de empresa de servicios públicos", norma: "Ley 142/1994", n: 15, u: "habiles" },
    { id: "reporte", nombre: "Aviso previo a reporte negativo", norma: "Ley 2157/2021", n: 20, u: "calendario" },
    { id: "preaviso", nombre: "Preaviso para entregar la vivienda", norma: "Ley 820/2003", n: 3, u: "meses" },
    { id: "querella", nombre: "Presentar querella penal", norma: "Ley 906/2004", n: 6, u: "meses" },
    { id: "laboral", nombre: "Prescripción de derechos laborales", norma: "CST art. 488", n: 3, u: "anios" },
  ];

  window.Terminos = { festivos, esFestivo, esHabil, contar, iso, TRAMITES };
})();
