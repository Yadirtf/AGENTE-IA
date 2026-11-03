/* Plantillas de documentos jurídicos básicos (Colombia). */
(function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const v = (x, ph) => (x && String(x).trim() ? esc(x) : `<span class="vacio">${esc(ph)}</span>`);
  const parrafos = (t, ph) => (t && t.trim()
    ? t.trim().split(/\n+/).map((p) => `<p>${esc(p)}</p>`).join("")
    : `<p><span class="vacio">${esc(ph)}</span></p>`);
  const hoy = () => new Date().toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" });

  const comunes = [
    { id: "nombre", label: "Su nombre completo", ph: "Nombre y apellidos" },
    { id: "cedula", label: "Cédula", ph: "C.C. 0.000.000" },
    { id: "ciudad", label: "Ciudad", ph: "Mocoa", valor: "Mocoa" },
    { id: "contacto", label: "Correo o dirección para notificaciones", ph: "correo@ejemplo.com" },
  ];

  const PLANTILLAS = [
    {
      id: "peticion", nombre: "Derecho de petición", desc: "Art. 23 C.P. · Ley 1755/2015",
      campos: [...comunes,
        { id: "destinatario", label: "Entidad o empresa", ph: "Alcaldía Municipal de Mocoa" },
        { id: "hechos", label: "Hechos (cuente qué pasó)", tipo: "area", ph: "Describa los hechos…" },
        { id: "peticion", label: "Qué solicita", tipo: "area", ph: "Solicito que…" }],
      render: (c) => `
        <p>${v(c.ciudad, "Ciudad")}, ${hoy()}</p>
        <p>Señores<br><b>${v(c.destinatario, "Entidad destinataria")}</b><br>E. S. D.</p>
        <p><b>Asunto:</b> Derecho de petición (artículo 23 de la Constitución Política y Ley 1755 de 2015).</p>
        <p>Yo, ${v(c.nombre, "nombre completo")}, identificado(a) con cédula de ciudadanía No. ${v(c.cedula, "número")}, en ejercicio del derecho fundamental de petición, respetuosamente me dirijo a ustedes con fundamento en los siguientes:</p>
        <h4>Hechos</h4>${parrafos(c.hechos, "Hechos del caso")}
        <h4>Petición</h4>${parrafos(c.peticion, "Lo que solicita")}
        <h4>Fundamentos de derecho</h4>
        <p>Artículo 23 de la Constitución Política; Ley 1755 de 2015, que establece un término de quince (15) días hábiles para resolver las peticiones, y de diez (10) días hábiles cuando se trate de solicitudes de documentos o información.</p>
        <h4>Notificaciones</h4><p>Recibiré respuesta en: ${v(c.contacto, "correo o dirección")}.</p>
        <p>Atentamente,</p><div class="firma">${v(c.nombre, "Nombre")}<br>C.C. ${v(c.cedula, "número")}</div>`,
    },
    {
      id: "tutela", nombre: "Acción de tutela", desc: "Art. 86 C.P. · Decreto 2591/1991",
      campos: [...comunes,
        { id: "accionado", label: "Contra quién (entidad o persona)", ph: "Nombre de la EPS / entidad" },
        { id: "derechos", label: "Derechos vulnerados", ph: "salud, vida digna, petición" },
        { id: "hechos", label: "Hechos", tipo: "area", ph: "Describa los hechos…" },
        { id: "peticion", label: "Qué le pide al juez", tipo: "area", ph: "Ordenar a … que en 48 horas…" },
        { id: "pruebas", label: "Pruebas que anexa", tipo: "area", ph: "Copia de la orden médica, radicado…" }],
      render: (c) => `
        <p>${v(c.ciudad, "Ciudad")}, ${hoy()}</p>
        <p>Señor(a)<br><b>JUEZ (REPARTO)</b><br>E. S. D.</p>
        <p><b>Referencia:</b> Acción de tutela<br><b>Accionante:</b> ${v(c.nombre, "su nombre")}<br><b>Accionado:</b> ${v(c.accionado, "entidad accionada")}</p>
        <p>Yo, ${v(c.nombre, "nombre completo")}, identificado(a) con C.C. ${v(c.cedula, "número")}, actuando en nombre propio, interpongo acción de tutela con fundamento en el artículo 86 de la Constitución Política y el Decreto 2591 de 1991, para que se protejan mis derechos fundamentales a ${v(c.derechos, "derechos vulnerados")}, con base en los siguientes:</p>
        <h4>Hechos</h4>${parrafos(c.hechos, "Hechos del caso")}
        <h4>Pretensiones</h4>${parrafos(c.peticion, "Lo que pide al juez")}
        <h4>Pruebas</h4>${parrafos(c.pruebas, "Lista de pruebas")}
        <h4>Juramento</h4><p>Manifiesto bajo la gravedad del juramento que no he presentado otra acción de tutela por los mismos hechos y derechos.</p>
        <h4>Notificaciones</h4><p>Accionante: ${v(c.contacto, "correo o dirección")}.</p>
        <p>Atentamente,</p><div class="firma">${v(c.nombre, "Nombre")}<br>C.C. ${v(c.cedula, "número")}</div>`,
    },
    {
      id: "garantia", nombre: "Reclamo por garantía", desc: "Ley 1480/2011",
      campos: [...comunes,
        { id: "destinatario", label: "Tienda o fabricante", ph: "Almacén …" },
        { id: "producto", label: "Producto y fecha de compra", ph: "Nevera marca X, comprada el …" },
        { id: "hechos", label: "Qué falla tiene", tipo: "area", ph: "Describa la falla…" },
        { id: "peticion", label: "Qué pide", tipo: "area", ph: "La reparación / el cambio / la devolución del dinero" }],
      render: (c) => `
        <p>${v(c.ciudad, "Ciudad")}, ${hoy()}</p>
        <p>Señores<br><b>${v(c.destinatario, "Proveedor")}</b></p>
        <p><b>Asunto:</b> Reclamación directa por garantía legal (Ley 1480 de 2011, Estatuto del Consumidor).</p>
        <p>Yo, ${v(c.nombre, "nombre completo")}, con C.C. ${v(c.cedula, "número")}, adquirí el producto ${v(c.producto, "producto y fecha")}, el cual presenta las siguientes fallas:</p>
        ${parrafos(c.hechos, "Descripción de la falla")}
        <h4>Solicitud</h4>${parrafos(c.peticion, "Reparación, cambio o devolución")}
        <p>De conformidad con el Estatuto del Consumidor, la garantía legal es responsabilidad solidaria del productor y del proveedor y su efectividad no tiene costo para el consumidor. Solicito respuesta dentro de los quince (15) días hábiles siguientes; de lo contrario acudiré a la Superintendencia de Industria y Comercio.</p>
        <p>Notificaciones: ${v(c.contacto, "correo o dirección")}.</p>
        <div class="firma">${v(c.nombre, "Nombre")}<br>C.C. ${v(c.cedula, "número")}</div>`,
    },
    {
      id: "habeas", nombre: "Reclamo habeas data", desc: "Ley 1266/2008 · Ley 2157/2021",
      campos: [...comunes,
        { id: "destinatario", label: "Banco, tienda o central de riesgo", ph: "Banco …" },
        { id: "hechos", label: "Qué pasó con el reporte", tipo: "area", ph: "Fui reportado sin aviso previo…" }],
      render: (c) => `
        <p>${v(c.ciudad, "Ciudad")}, ${hoy()}</p>
        <p>Señores<br><b>${v(c.destinatario, "Fuente de información")}</b></p>
        <p><b>Asunto:</b> Reclamo por reporte negativo — derecho de habeas data (Ley 1266 de 2008 modificada por la Ley 2157 de 2021).</p>
        <p>Yo, ${v(c.nombre, "nombre completo")}, con C.C. ${v(c.cedula, "número")}, presento reclamo con base en los siguientes hechos:</p>
        ${parrafos(c.hechos, "Hechos")}
        <h4>Solicitud</h4>
        <ol><li>Copia de la comunicación previa al reporte y de la prueba de su envío.</li><li>Copia de la autorización para el tratamiento de mis datos ante centrales de riesgo.</li><li>Si no existen, la eliminación inmediata del reporte negativo.</li></ol>
        <p>La ley exige comunicación previa con al menos veinte (20) días calendario de anticipación al reporte. Solicito respuesta dentro de los quince (15) días hábiles siguientes.</p>
        <p>Notificaciones: ${v(c.contacto, "correo o dirección")}.</p>
        <div class="firma">${v(c.nombre, "Nombre")}<br>C.C. ${v(c.cedula, "número")}</div>`,
    },
    {
      id: "preaviso", nombre: "Preaviso de arrendamiento", desc: "Ley 820/2003 art. 24",
      campos: [...comunes,
        { id: "destinatario", label: "Nombre del arrendador", ph: "Sr(a). …" },
        { id: "inmueble", label: "Dirección del inmueble", ph: "Calle …, barrio …" },
        { id: "fecha_entrega", label: "Fecha en que entregará", tipo: "date", ph: "fecha" }],
      render: (c) => `
        <p>${v(c.ciudad, "Ciudad")}, ${hoy()}</p>
        <p>Señor(a)<br><b>${v(c.destinatario, "Arrendador")}</b></p>
        <p><b>Asunto:</b> Preaviso de terminación del contrato de arrendamiento.</p>
        <p>Yo, ${v(c.nombre, "nombre completo")}, identificado(a) con C.C. ${v(c.cedula, "número")}, en calidad de arrendatario(a) del inmueble ubicado en ${v(c.inmueble, "dirección")}, le comunico mi decisión de dar por terminado el contrato de arrendamiento, con un preaviso no inferior a tres (3) meses conforme al artículo 24 de la Ley 820 de 2003.</p>
        <p>Entregaré el inmueble el día ${v(c.fecha_entrega && new Date(c.fecha_entrega + "T12:00").toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" }), "fecha de entrega")}, a paz y salvo por concepto de cánones y servicios públicos.</p>
        <p>Notificaciones: ${v(c.contacto, "correo o dirección")}.</p>
        <div class="firma">${v(c.nombre, "Nombre")}<br>C.C. ${v(c.cedula, "número")}</div>`,
    },
    {
      id: "conciliacion", nombre: "Solicitud de conciliación", desc: "Ley 2220/2022",
      campos: [...comunes,
        { id: "destinatario", label: "Centro de conciliación", ph: "Consultorio jurídico / Comisaría de Familia" },
        { id: "convocado", label: "Persona a citar (nombre y dirección)", ph: "Nombre, dirección y teléfono" },
        { id: "hechos", label: "Hechos", tipo: "area", ph: "Describa el conflicto…" },
        { id: "peticion", label: "Qué propone o pretende", tipo: "area", ph: "Fijar una cuota alimentaria de… / un plan de pagos…" }],
      render: (c) => `
        <p>${v(c.ciudad, "Ciudad")}, ${hoy()}</p>
        <p>Señores<br><b>${v(c.destinatario, "Centro de conciliación")}</b></p>
        <p><b>Asunto:</b> Solicitud de audiencia de conciliación (Ley 2220 de 2022).</p>
        <p><b>Convocante:</b> ${v(c.nombre, "nombre completo")}, C.C. ${v(c.cedula, "número")}.<br><b>Convocado(a):</b> ${v(c.convocado, "nombre y dirección de la otra parte")}.</p>
        <p>Solicito respetuosamente se fije fecha y hora para celebrar audiencia de conciliación con fundamento en los siguientes:</p>
        <h4>Hechos</h4>${parrafos(c.hechos, "Hechos del conflicto")}
        <h4>Pretensiones</h4>${parrafos(c.peticion, "Lo que propone")}
        <h4>Notificaciones</h4><p>Convocante: ${v(c.contacto, "correo o dirección")}.</p>
        <div class="firma">${v(c.nombre, "Nombre")}<br>C.C. ${v(c.cedula, "número")}</div>`,
    },
  ];

  window.Plantillas = PLANTILLAS;
})();
