"""api.py · API JSON para las ESP32 de la maqueta (entrada y salida).

Las ESP32 hablan con Flask por WiFi (HTTP + JSON). Todas las rutas piden el encabezado
`X-API-Key` (config.ESP32_TOKEN) para que otro aparato de la red no pueda abrir la barrera.

  POST /api/entrada/estado    la ESP32 de entrada reporta sus 4 cajones (cada 5 s)
  POST /api/entrada/vehiculo  llegó un carro: pide a la cámara que lea la placa y responde si abre
  POST /api/salida/vehiculo   llegó un carro a la salida: pide a la cámara que lea la placa
  POST /api/salida/nfc        pasaron la tarjeta NFC: cobra (simulado) y ¿abro? (placa de la cámara de salida)

La seguridad antiatropello NO depende de esta API: se queda en la ESP32.
Cuando el sensor ve un carro, la ESP32 manda "nuevo": true en su primera pregunta: se descartan lecturas viejas
y queda una solicitud en `solicitudes_camara`. main.py la ve, lee la placa con la cámara de ese lado (sin teclas) y deja
el resultado en `lecturas_camara`; cada lectura se usa una sola vez.
"""
import hmac
from datetime import timedelta

from flask import Blueprint, jsonify, request

import config
import logic as L
from models import CameraReading, CameraRequest, Plate, Spot, db

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.before_request
def _token():
    enviado = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(enviado.encode(), config.ESP32_TOKEN.encode()):
        return jsonify(ok=False, error="Clave de API incorrecta"), 401


def _lectura(side):
    """Lectura más reciente de esa cámara que todavía no caduca, o None."""
    limite = L.now() - timedelta(seconds=config.LECTURA_TTL)
    return (CameraReading.query.filter(CameraReading.side == side, CameraReading.at >= limite)
            .order_by(CameraReading.at.desc(), CameraReading.id.desc()).first())


def _consumir(side):
    """Borra las lecturas (y la solicitud) de esa cámara: una lectura sirve para un solo paso de la barrera."""
    CameraReading.query.filter_by(side=side).delete()
    CameraRequest.query.filter_by(side=side).delete()
    db.session.commit()


def _pedir_lectura(side):
    """Le pide a la cámara de ese lado que lea la placa (la renueva cada vez que la ESP32 pregunta)."""
    n = L.now()
    r = db.session.get(CameraRequest, side)
    if r:
        r.at = n
    else:
        db.session.add(CameraRequest(side=side, at=n))
    db.session.commit()


def _nuevo_ciclo(side):
    """Llegó un carro distinto: se descarta cualquier lectura que haya quedado de otro."""
    if (request.get_json(silent=True) or {}).get("nuevo"):
        _consumir(side)


# ------------------------------------------------------------------ ENTRADA
@bp.post("/entrada/estado")
def entrada_estado():
    """Body: {"cajones": [true, false, ...]}  (true = ocupado). Se guarda en `lugares` (sensor_busy)."""
    data = request.get_json(silent=True) or {}
    cajones = data.get("cajones")
    if not isinstance(cajones, list):
        return jsonify(ok=False, error='Falta "cajones" (lista de true/false)'), 400
    n = L.now()
    for code, busy in zip(config.ESP32_SPOTS, cajones):
        s = db.session.get(Spot, code)
        if s:
            s.sensor_busy, s.sensor_at = bool(busy), n
    db.session.commit()
    return jsonify(ok=True, libres_web=L.count_free())


@bp.post("/entrada/vehiculo")
def entrada_vehiculo():
    """La ESP32 vio un carro en la entrada. Responde {"abrir": true, "placa", "cajon"} o {"abrir": false, "motivo"}.
    motivo = esperando_placa significa "todavía no hay lectura de la cámara, vuelve a preguntar"."""
    _nuevo_ciclo("entrada")
    lec = _lectura("entrada")
    if not lec:
        _pedir_lectura("entrada")  # la cámara de entrada lee la placa sola (main.py)
        return jsonify(ok=True, abrir=False, motivo="esperando_placa", msg="Esperando la lectura de la placa")
    p = Plate.query.filter_by(plate_norm=lec.plate_norm).first()
    res = L.register_entry(lec.plate_norm, source="camara", vehicle_type=p.vehicle_type if p else None,
                           only_known=True)
    _consumir("entrada")  # sea cual sea la respuesta, esa lectura ya se usó
    st, r = res["status"], res["r"]
    if st in ("walkin", "checkin"):
        return jsonify(ok=True, abrir=True, placa=r.plate, cajon=r.spot, msg=res["msg"])
    return jsonify(ok=True, abrir=False, motivo=st, msg=res["msg"])


# ------------------------------------------------------------------ SALIDA
@bp.post("/salida/vehiculo")
def salida_vehiculo():
    """Hay un carro en la salida: pide a la cámara de salida que lea la placa. {"lectura": true} = ya hay una."""
    _nuevo_ciclo("salida")
    if _lectura("salida"):
        return jsonify(ok=True, lectura=True)
    _pedir_lectura("salida")
    return jsonify(ok=True, lectura=False)


@bp.post("/salida/nfc")
def salida_nfc():
    """Body: {"uid": "04A1B2C3"}. El pago NFC es SIMULADO: cualquier tarjeta cobra lo que se debe
    (pago con método 'tarjeta' y folio nuevo; no se guarda el UID de la tarjeta).
    Responde {"autorizado": true, "placa", "cobrado"} o {"autorizado": false, "motivo"}."""
    data = request.get_json(silent=True) or {}
    if not str(data.get("uid", "")).strip():
        return jsonify(ok=False, error='Falta "uid"'), 400
    lec = _lectura("salida")
    if not lec:
        return jsonify(ok=True, autorizado=False, motivo="sin_placa",
                       msg="La cámara de salida no ha leído ninguna placa")
    v = L.inside_by_plate(lec.plate_norm)
    if not v:
        _consumir("salida")
        return jsonify(ok=True, autorizado=False, motivo="notfound",
                       msg=f"No hay un vehículo dentro con la placa {L.fmt_plate(lec.plate_norm)}")
    debe = L.due_of(v)
    if debe > 0:
        L.add_payment(v, "tarjeta", ref=L.new_folio(), amount=debe)
    L.do_exit(v)
    _consumir("salida")
    return jsonify(ok=True, autorizado=True, placa=v.plate, cobrado=debe, msg=f"Salida registrada: {v.plate}")
