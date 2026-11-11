"""Prueba la agenda por voz sin base de datos ni modelos:  python -m scripts.probar_agenda

Simula conversaciones completas con Amparo y verifica que respete días hábiles, festivos y horas libres.
"""
from datetime import date

from app import agenda

ENTIDADES = [{"id": 1, "nombre": "Consultorio jurídico universitario"}, {"id": 2, "nombre": "Casa de Justicia"},
             {"id": 3, "nombre": "Comisaría de Familia de Mocoa"}, {"id": 4, "nombre": "Personería Municipal de Mocoa"},
             {"id": 5, "nombre": "Defensoría del Pueblo · Regional Putumayo"}]
HOY = date(2026, 11, 11)     # miércoles; el lunes 16 de noviembre de 2026 es festivo (Independencia de Cartagena)
OCUPADAS = {(1, "2026-11-12"): {"08:00", "09:00"}, (1, "2026-11-13"): set(agenda.HORAS)}
creadas: list[dict] = []


def libres(eid, d):
    return [h for h in agenda.HORAS if h not in OCUPADAS.get((eid, d.isoformat()), set())]


def crear(datos):
    if datos["hora"] in OCUPADAS.get((datos["entidad_id"], datos["fecha"]), set()):
        raise agenda.HorarioOcupado()
    creadas.append(datos)
    OCUPADAS.setdefault((datos["entidad_id"], datos["fecha"]), set()).add(datos["hora"])
    return {"id": len(creadas), **datos}


def conversar(turnos, titulo):
    print(f"\n=== {titulo} ===")
    ctx = agenda.Contexto(ENTIDADES, libres, crear, hoy=HOY, alias="Mafe")
    estado, res = None, None
    for i, t in enumerate(turnos):
        res = agenda.procesar(t, estado if i else None, ctx, motivo="La EPS no me entrega el medicamento")
        print(f"👤 {t}")
        print("🤖 " + " ".join(f["texto"] for f in res.frases))
        estado = res.estado
        if estado is None:
            break
    return res


def main():
    # Partes de la lógica
    assert agenda.es_festivo(date(2026, 11, 16)) and agenda.es_festivo(date(2026, 11, 2))
    assert not agenda.es_habil(date(2026, 11, 14)) and agenda.es_habil(date(2026, 11, 12))
    assert agenda.es_festivo(date(2026, 4, 3)) == "Viernes Santo"
    assert agenda.digitos_hablados("tres diez, cero cero cero, cero cero cero cero") == "3100000000"
    assert agenda.digitos_hablados("trescientos diez 555 12 34") == "3105551234"
    assert agenda.buscar_hora("a las dos de la tarde") == ("14:00", None)
    assert agenda.buscar_hora("a las 9 a.m.") == ("09:00", None)
    assert agenda.buscar_hora("a las tres") == ("15:00", None)
    assert agenda.buscar_hora("nueve") == ("09:00", None)
    assert agenda.buscar_hora("en la tarde") == (None, "tarde")
    assert agenda.buscar_fecha("mañana a las 9 de la mañana", HOY) == date(2026, 11, 12)
    assert agenda.buscar_fecha("el jueves", HOY) == date(2026, 11, 12)
    assert agenda.buscar_fecha("el próximo martes", HOY) == date(2026, 11, 17)
    assert agenda.buscar_fecha("el diecinueve de noviembre", HOY) == date(2026, 11, 19)
    assert agenda.buscar_fecha("el 5", HOY) == date(2026, 12, 5)
    assert agenda.buscar_fecha("en una semana", HOY, solo_explicita=True) is None
    assert agenda.limpiar_nombre("Sí, mi nombre es maría fernanda jojoa.") == "María Fernanda Jojoa"
    assert agenda.quiere_agendar("quiero agendar una cita")
    assert agenda.quiere_agendar("necesito una cita con el consultorio")
    assert not agenda.quiere_agendar("la EPS no me da la cita médica")
    assert agenda.acepta_oferta("sí, por favor", "¿Quiere que le agende una cita gratuita?")

    # Conversación completa, paso a paso
    r = conversar(["Quiero agendar una cita", "en el consultorio", "el sábado", "sí", "a las 10", "presencial",
                   "me llamo María Fernanda Jojoa", "310 000 0000", "sin cédula", "sí autorizo", "sí, confírmela"],
                  "Paso a paso (rechaza el sábado)")
    assert r.cita and r.cita["fecha"] == "2026-11-17" and r.cita["hora"] == "10:00", r.cita

    # Todo de una vez, con festivo y hora ocupada
    r = conversar(["Agéndeme una cita presencial en la personería el lunes a las 9",
                   "entonces el martes", "Pedro Pérez", "tres uno cinco dos dos dos tres tres tres tres",
                   "1124000111", "sí", "no, mejor a las once", "sí"], "Festivo y cambio de hora al confirmar")
    assert r.cita and r.cita["fecha"] == "2026-11-17" and r.cita["hora"] == "11:00" and r.cita["documento"] == "1124000111"

    # Hora ocupada y día lleno
    r = conversar(["quiero una cita", "el que usted me recomiende", "el viernes", "el jueves", "a las 8",
                   "en la tarde", "virtual", "Ana", "3001112233", "no", "sí", "sí"], "Día lleno y hora ocupada")
    assert r.cita and r.cita["fecha"] == "2026-11-12" and r.cita["hora"] == "14:00" and r.cita["modalidad"] == "virtual"

    # Cancelar
    r = conversar(["quiero agendar una cita", "mejor cancele"], "Cancelar")
    assert r.cancelada

    # Sin autorización
    r = conversar(["agendar cita en la casa de justicia mañana a las 3 por teléfono", "Luis Gómez", "3209998877",
                   "sin cédula", "no autorizo"], "Sin autorización de datos")
    assert r.cancelada and len(creadas) == 3
    print("\nTodo bien ✔")


if __name__ == "__main__":
    main()
