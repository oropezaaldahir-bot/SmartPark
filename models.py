"""models.py · Tablas de la base de datos (SQLAlchemy).
El mismo esquema, en SQL puro, está en schema.sql."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Reservation(db.Model):
    """Una visita: reservada, dentro del estacionamiento, terminada o cancelada."""

    __tablename__ = "reservaciones"

    code = db.Column(db.String(10), primary_key=True)  # SP-1234
    plate = db.Column(db.String(10), nullable=False)  # ABC-123
    spot = db.Column(db.String(3), nullable=False, index=True)  # A01..F08
    start = db.Column(db.DateTime, nullable=False)  # hora de llegada prevista
    checkin = db.Column(db.DateTime)  # hora real de entrada
    exit_at = db.Column(db.DateTime)  # hora de salida
    # hold = apartado mientras se paga · reserved · in · done · cancelled · expired
    status = db.Column(db.String(10), nullable=False, index=True)
    hold_until = db.Column(db.DateTime)
    walkin = db.Column(db.Boolean, nullable=False, default=False)
    vehicle_type = db.Column(db.String(12))  # Automóvil | Motocicleta | Camión (lo detecta la cámara)
    source = db.Column(db.String(10), default="web")  # web | camara | admin
    # Tarifa de reservación (se paga al reservar). Nunca datos de tarjeta: solo método y folio.
    fee_amount = db.Column(db.Integer)
    fee_at = db.Column(db.DateTime)
    fee_method = db.Column(db.String(10))  # tarjeta | efectivo
    fee_ref = db.Column(db.String(20))  # folio de la pasarela

    payments = db.relationship(
        "Payment", backref="reservation", order_by="Payment.at", cascade="all, delete-orphan"
    )


class Payment(db.Model):
    """Pagos del estacionamiento. Solo método, monto y folio; jamás datos de tarjeta."""

    __tablename__ = "pagos"

    id = db.Column(db.Integer, primary_key=True)
    reservation_code = db.Column(db.String(10), db.ForeignKey("reservaciones.code"), nullable=False, index=True)
    at = db.Column(db.DateTime, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    method = db.Column(db.String(10), nullable=False)  # tarjeta | efectivo
    ref = db.Column(db.String(20))


class Plate(db.Model):
    """Placas que la cámara ya detectó y guardó. Solo estas (más reservas y empleados) pueden entrar por /acceso."""

    __tablename__ = "placas"

    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(10), nullable=False)  # ABC-123
    plate_norm = db.Column(db.String(10), nullable=False, unique=True)  # ABC123 (para comparar)
    vehicle_type = db.Column(db.String(12))  # Automóvil | Motocicleta | Camión
    first_seen = db.Column(db.DateTime, nullable=False)
    last_seen = db.Column(db.DateTime, nullable=False)
    hits = db.Column(db.Integer, nullable=False, default=1)  # veces que la cámara la detectó


class Employee(db.Model):
    __tablename__ = "empleados"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False)
    plate = db.Column(db.String(10), nullable=False)  # ABC-123
    plate_norm = db.Column(db.String(10), nullable=False, unique=True)  # ABC123 (para comparar)
