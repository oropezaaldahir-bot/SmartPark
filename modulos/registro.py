"""Módulo de registro: conecta el reconocimiento de placas con la base de datos de SmartPark.

Usa la MISMA base de datos (config.DATABASE_URL) y las MISMAS reglas que la página web
(logic.register_entry): si la placa tiene reserva la confirma, si ya está dentro lo avisa
y si no, le asigna el primer cajón libre. Lo que registra la cámara aparece al instante
en el panel de administrador.
"""
from app import app  # al importar crea las tablas si no existen
import logic as L
from models import db


def registrar_entrada(placa: str, tipo: str = None):
    """Registra la entrada de una placa. Devuelve (estado, mensaje para mostrar).

    estado: walkin | checkin | inside | early | full | invalid | error
    Nunca lanza excepciones: si la base falla devuelve ("error", mensaje).
    """
    with app.app_context():
        try:
            res = L.register_entry(placa, source="camara", vehicle_type=tipo)
        except Exception as e:  # base caída, bloqueada, mal configurada...
            db.session.rollback()
            print(f"[BD] Error al registrar {placa}: {e}")
            return "error", "No se pudo guardar en la base de datos"
        r = res["r"]
        msg = res["msg"] + (f" Boleto {r.code}" if r and res["status"] in ("walkin", "checkin", "inside") else "")
        return res["status"], msg
