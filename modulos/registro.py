"""Módulo de registro: conecta el reconocimiento de placas con la base de datos de SmartPark.

CÁMARA DE ENTRADA: la cámara GUARDA cada placa que lee en la tabla `placas` (misma base que la web, config.DATABASE_URL).
Después, en la página /acceso solo se deja entrar a las placas que están guardadas
(o que tienen reserva / son de un empleado). Así la cámara es quien da de alta los vehículos.
"""
from app import app  # al importar crea las tablas si no existen
import logic as L
from models import db


def registrar_placa(placa: str, tipo: str = None):
    """Guarda una placa detectada. Devuelve (estado, mensaje para mostrar).

    estado: new | known | invalid | error
    Nunca lanza excepciones: si la base falla devuelve ("error", mensaje).
    """
    with app.app_context():
        try:
            estado, p = L.save_plate(placa, tipo)
        except Exception as e:  # base caída, bloqueada, mal configurada...
            db.session.rollback()
            print(f"[BD] Error al guardar {placa}: {e}")
            return "error", "No se pudo guardar en la base de datos"
        if estado == "invalid":
            return "invalid", "Placa incompleta, no se guardó."
        if estado == "new":
            return "new", f"Placa {p.plate} guardada. Ya puede ingresar."
        return "known", f"Placa {p.plate} ya estaba guardada."


# ------------------------------------------------------------------ cámara de SALIDA
def consultar_salida(placa: str):
    """Busca la tarifa de la placa SIN modificar nada. Devuelve (estado, mensaje):
    notfound | pay (debe pagar) | ok (ya pagó, puede salir) | invalid | error"""
    with app.app_context():
        try:
            if len(L.norm(placa)) < 5:
                return "invalid", "Placa incompleta."
            r = L.inside_by_plate(placa)
            if not r:
                return "notfound", f"No hay un vehículo dentro con la placa {L.fmt_plate(L.norm(placa)[:7])}."
            due = L.due_of(r)
            if due > 0:
                return "pay", f"{r.plate}: dentro {L.fmt_dur(L.now() - r.checkin)}. Debe pagar {L.money(due)} (boleto {r.code})."
            return "ok", f"{r.plate}: pago listo. Puede salir."
        except Exception as e:
            db.session.rollback()
            print(f"[BD] Error al consultar {placa}: {e}")
            return "error", "No se pudo consultar la base de datos"


def registrar_salida(placa: str):
    """Deja salir SOLO si ya pagó: registra la salida y borra la placa de la base.
    Devuelve (estado, mensaje): exit | pay | notfound | invalid | error"""
    with app.app_context():
        try:
            if len(L.norm(placa)) < 5:
                return "invalid", "Placa incompleta."
            r = L.inside_by_plate(placa)
            if not r:
                return "notfound", f"No hay un vehículo dentro con la placa {L.fmt_plate(L.norm(placa)[:7])}."
            due = L.due_of(r)
            if due > 0:
                return "pay", f"NO puede salir: debe pagar {L.money(due)} (boleto {r.code})."
            L.do_exit(r)
            return "exit", f"Salida registrada: {r.plate}. Placa eliminada. ¡Buen viaje!"
        except Exception as e:
            db.session.rollback()
            print(f"[BD] Error al registrar salida de {placa}: {e}")
            return "error", "No se pudo guardar en la base de datos"
