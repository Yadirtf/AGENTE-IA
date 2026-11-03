-- =====================================================================
--  Datos de referencia (catálogos). Se recargan en cada ingesta.
--  NOTA: verifique siempre direcciones y horarios en los canales oficiales.
-- =====================================================================
TRUNCATE rutas, entidades RESTART IDENTITY;

INSERT INTO areas (slug, nombre, descripcion, color, simbolo) VALUES
('derechos_fundamentales','Derechos fundamentales',
 'Derecho de petición a entidades públicas o privadas que no responden, acción de tutela para proteger derechos fundamentales vulnerados, debido proceso, mínimo vital, igualdad, educación.',
 '#7A1F2B','§'),
('laboral','Trabajo y empleo',
 'Despido sin justa causa, liquidación, salario no pagado, prestaciones sociales, prima, cesantías, vacaciones, contrato de trabajo, jornada laboral, horas extra, acoso laboral, seguridad social del trabajador.',
 '#2F5D50','⚒'),
('consumidor','Consumidor',
 'Producto defectuoso, garantía, devolución de dinero, derecho de retracto en compras por internet, publicidad engañosa, cobros indebidos de una tienda, reclamos a empresas, servicios públicos domiciliarios, facturas de agua, luz, gas, telefonía.',
 '#B0702C','⚖'),
('arrendamiento','Arrendamiento de vivienda',
 'Contrato de arriendo de vivienda, incremento del canon, depósito, desalojo, el arrendador o casero no devuelve la plata, terminación del contrato, preaviso, reparaciones del inmueble.',
 '#5B4B8A','⌂'),
('familia','Familia',
 'Cuota alimentaria para hijos, custodia, régimen de visitas, divorcio, separación, unión marital de hecho, reconocimiento de paternidad, inasistencia alimentaria.',
 '#3D6B8C','❦'),
('violencia','Violencia intrafamiliar y de género',
 'Violencia intrafamiliar, maltrato, agresión física o psicológica de la pareja, amenazas, violencia contra la mujer, abuso a niños, niñas y adolescentes, medidas de protección.',
 '#A3242C','✚'),
('deudas','Deudas, cobranzas y datos personales',
 'Reportes negativos en centrales de riesgo, Datacrédito, cobros de deudas, llamadas de cobranza abusivas, habeas data, protección de datos personales, embargos por deudas.',
 '#6B6B2F','◈'),
('salud','Salud',
 'EPS que niega medicamentos, citas, cirugías, tratamientos o procedimientos, derecho fundamental a la salud, quejas ante la Superintendencia de Salud, afiliación.',
 '#2C7A7B','✛'),
('penal','Penal y denuncias',
 'Denunciar un delito, hurto, robo, estafa, lesiones personales, amenazas, injuria y calumnia, derechos de las víctimas, querella, Fiscalía.',
 '#3A3A3A','⚔'),
('victimas','Víctimas del conflicto armado',
 'Víctimas del conflicto armado, desplazamiento forzado, despojo de tierras, declaración ante el Ministerio Público, Registro Único de Víctimas, reparación integral, Ley de Víctimas.',
 '#8C5A3D','✦')
ON CONFLICT (slug) DO UPDATE
   SET nombre = EXCLUDED.nombre, descripcion = EXCLUDED.descripcion,
       color = EXCLUDED.color, simbolo = EXCLUDED.simbolo;

-- ---------------------------------------------------------------------
-- Rutas de acción por área (pasos ordenados)
-- ---------------------------------------------------------------------
INSERT INTO rutas (area_slug, orden, titulo, detalle, plazo) VALUES
('derechos_fundamentales',1,'Presente un derecho de petición','Por escrito o verbalmente, ante la entidad. Pida radicado o número de constancia.','Respuesta: 15 días hábiles'),
('derechos_fundamentales',2,'Guarde las pruebas','Copia de la petición, radicado, correos y cualquier respuesta incompleta.',NULL),
('derechos_fundamentales',3,'Si no responden o vulneran un derecho: tutela','Puede presentarla usted mismo, sin abogado, ante cualquier juez (reparto).','Fallo: 10 días'),
('derechos_fundamentales',4,'Si el fallo no le favorece, impúgnelo','Escrito sencillo explicando por qué no está de acuerdo.','3 días desde la notificación'),

('laboral',1,'Reúna pruebas de la relación laboral','Contrato, desprendibles de pago, mensajes, testigos, carta de despido.',NULL),
('laboral',2,'Solicite por escrito la liquidación','Pida al empleador el pago de salarios, prestaciones e indemnización si aplica.',NULL),
('laboral',3,'Acuda a la Inspección de Trabajo','El Ministerio del Trabajo puede citar a conciliación gratuita.',NULL),
('laboral',4,'Demanda laboral','Si no hay acuerdo. Un consultorio jurídico o la Defensoría pueden orientarle.','Prescripción: 3 años'),

('consumidor',1,'Reclame directamente al proveedor','Por escrito, explicando la falla y lo que pide (reparación, cambio o devolución).','Respuesta: 15 días hábiles'),
('consumidor',2,'Conserve factura y evidencias','Factura, garantía, fotos, chats, publicidad.',NULL),
('consumidor',3,'Acción de protección al consumidor','Ante la Superintendencia de Industria y Comercio, en línea y sin abogado.','Hasta 1 año tras vencer la garantía'),

('arrendamiento',1,'Revise el contrato y los pagos','Fecha de inicio, canon, prórrogas, recibos de pago.',NULL),
('arrendamiento',2,'Comunique por escrito','Reclamos, preavisos y acuerdos deben quedar por escrito con constancia.','Preaviso: 3 meses'),
('arrendamiento',3,'Concilie','Centro de conciliación gratuito, Casa de Justicia o consultorio jurídico.',NULL),
('arrendamiento',4,'Proceso judicial','Solo un juez puede ordenar una restitución (desalojo).',NULL),

('familia',1,'Solicite audiencia de conciliación','Comisaría de Familia, ICBF, consultorio jurídico o centro de conciliación.','Requisito previo a la demanda'),
('familia',2,'Lleve los soportes','Registro civil de los hijos, gastos, ingresos del obligado.',NULL),
('familia',3,'Si incumplen el acuerdo','Demanda ejecutiva de alimentos o denuncia por inasistencia alimentaria.',NULL),

('violencia',1,'Póngase a salvo','Si hay peligro inmediato llame al 123. Línea 155 orientación a mujeres. Línea 141 ICBF.','Inmediato'),
('violencia',2,'Pida medidas de protección','Comisaría de Familia (o juez si no existe en su municipio).',NULL),
('violencia',3,'Denuncie','Fiscalía (URI/SAU) o en línea. La violencia intrafamiliar se investiga de oficio.',NULL),
('violencia',4,'Busque acompañamiento','Atención psicosocial, Defensoría del Pueblo, Personería.',NULL),

('deudas',1,'Pida información a la entidad','Solicite estado de la deuda y la autorización del reporte.',NULL),
('deudas',2,'Presente un reclamo de habeas data','Ante la fuente (banco, tienda) o la central de riesgo.','Respuesta: 15 días hábiles'),
('deudas',3,'Queja ante la SIC','Si no responden o la cobranza es abusiva.',NULL),

('salud',1,'Radique PQRS ante la EPS','Pida por escrito la autorización o entrega, con la orden médica.',NULL),
('salud',2,'Queja ante la Supersalud','Si la EPS no responde o niega el servicio.',NULL),
('salud',3,'Acción de tutela','Si está en riesgo su salud o su vida; puede pedir medida provisional.','Fallo: 10 días'),

('penal',1,'Preserve las pruebas','Fotos, mensajes, testigos, dictamen médico.',NULL),
('penal',2,'Presente denuncia o querella','Fiscalía (URI, SAU), Policía o denuncia virtual.','Querella: 6 meses'),
('penal',3,'Conciliación previa si es querellable','En delitos querellables se intenta conciliar antes del proceso.',NULL),

('victimas',1,'Rinda declaración','Ante el Ministerio Público: Personería, Defensoría o Procuraduría.',NULL),
('victimas',2,'Seguimiento a su inclusión en el RUV','Consulte su estado ante la Unidad para las Víctimas.',NULL),
('victimas',3,'Solicite atención y reparación','Ayuda humanitaria, retornos, restitución de tierras.',NULL);

-- ---------------------------------------------------------------------
-- Directorio de entidades (Putumayo y nacionales)
-- ---------------------------------------------------------------------
INSERT INTO entidades (nombre, tipo, municipio, contacto, canal, gratuito, areas, nota) VALUES
('Línea de emergencias','Emergencias','Nacional','123','Teléfono',TRUE,'{violencia,penal}','Peligro inmediato.'),
('Línea 155 · Orientación a mujeres','Orientación','Nacional','155','Teléfono 24 h',TRUE,'{violencia}','Orientación psicosocial y jurídica a mujeres víctimas de violencia.'),
('Línea 141 · ICBF','Protección infancia','Nacional','141','Teléfono 24 h',TRUE,'{violencia,familia}','Niños, niñas y adolescentes en riesgo.'),
('Línea 122 · Fiscalía','Denuncias','Nacional','122','Teléfono',TRUE,'{penal,violencia}','Orientación para denunciar.'),
('Línea 120 · Ministerio del Trabajo','Laboral','Nacional','120','Teléfono',TRUE,'{laboral}','Orientación en derechos laborales.'),
('Personería Municipal de Mocoa','Ministerio Público','Mocoa','Alcaldía de Mocoa','Presencial',TRUE,'{derechos_fundamentales,victimas,salud,deudas,consumidor}','Ayuda con peticiones, tutelas y declaración de víctimas.'),
('Comisaría de Familia de Mocoa','Familia','Mocoa','Alcaldía de Mocoa','Presencial',TRUE,'{familia,violencia}','Medidas de protección y conciliación en familia.'),
('ICBF · Regional Putumayo','Familia','Mocoa','icbf.gov.co','Presencial / web',TRUE,'{familia,violencia}','Defensor de familia, alimentos, custodia.'),
('Defensoría del Pueblo · Regional Putumayo','Ministerio Público','Mocoa','defensoria.gov.co','Presencial / web',TRUE,'{derechos_fundamentales,victimas,laboral,penal,salud}','Defensoría pública y orientación.'),
('Fiscalía · Seccional Putumayo','Denuncias','Mocoa','fiscalia.gov.co','Presencial / denuncia virtual',TRUE,'{penal,violencia}','Recepción de denuncias (SAU / URI).'),
('Inspección de Trabajo · Putumayo','Laboral','Mocoa','mintrabajo.gov.co','Presencial / web',TRUE,'{laboral}','Conciliación laboral gratuita.'),
('Consultorio jurídico universitario','Orientación','Putumayo','Universidades con programa de Derecho','Presencial',TRUE,'{derechos_fundamentales,laboral,consumidor,arrendamiento,familia,deudas,penal}','Estudiantes supervisados atienden a personas de escasos recursos.'),
('Casa de Justicia','Acceso a la justicia','Putumayo','Alcaldía municipal','Presencial',TRUE,'{familia,arrendamiento,violencia,penal,consumidor}','Reúne varias entidades en un solo lugar.'),
('Superintendencia de Industria y Comercio','Consumidor / datos','Nacional','sic.gov.co','Web',TRUE,'{consumidor,deudas}','Demandas de consumidor y quejas de habeas data, en línea.'),
('Superintendencia Nacional de Salud','Salud','Nacional','supersalud.gov.co','Web / teléfono',TRUE,'{salud}','Quejas contra EPS e IPS.'),
('Superintendencia de Servicios Públicos','Servicios públicos','Nacional','superservicios.gov.co','Web',TRUE,'{consumidor}','Recursos contra empresas de agua, luz y gas.'),
('Unidad para las Víctimas','Víctimas','Nacional','unidadvictimas.gov.co','Web / presencial',TRUE,'{victimas}','Registro, atención y reparación.');
