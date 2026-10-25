"""Módulo de registro: conecta el reconocimiento de placas con la base de datos de SmartPark.

La cámara GUARDA cada placa que lee en la tabla `placas` (misma base que la web, config.DATABASE_URL).
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
