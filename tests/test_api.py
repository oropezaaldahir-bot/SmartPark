"""Pruebas de la API de las ESP32 (/api). Ejecuta con:  python -m pytest -q"""
import os
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import config  # noqa: E402
import logic as L  # noqa: E402
from app import app  # noqa: E402
from models import CameraReading, Reservation, Spot, db  # noqa: E402
from modulos import registro  # noqa: E402

H = {"X-API-Key": config.ESP32_TOKEN}


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.app_context():
        db.drop_all()
        db.create_all()
        L.seed_spots()
    with app.test_client() as c:
        yield c


def test_sin_clave_no_entra(client):
    assert client.post("/api/entrada/vehiculo").status_code == 401
    assert client.post("/api/entrada/vehiculo", headers={"X-API-Key": "mala"}).status_code == 401


def test_estado_guarda_sensores(client):
    r = client.post("/api/entrada/estado", json={"cajones": [True, False, True, False]}, headers=H)
    assert r.get_json()["ok"] is True
    with app.app_context():
        assert db.session.get(Spot, "A01").sensor_busy is True
        assert db.session.get(Spot, "A02").sensor_busy is False
        assert db.session.get(Spot, "A04").sensor_at is not None
        assert db.session.get(Spot, "B01").sensor_busy is None  # sin sensor
    assert client.post("/api/entrada/estado", json={}, headers=H).status_code == 400


def test_entrada_espera_la_placa(client):
    j = client.post("/api/entrada/vehiculo", headers=H).get_json()
    assert j["abrir"] is False and j["motivo"] == "esperando_placa"


def test_entrada_abre_con_la_lectura_de_la_camara(client):
    assert registro.registrar_placa("ABC-123", "Automóvil")[0] == "new"
    j = client.post("/api/entrada/vehiculo", headers=H).get_json()
    assert j["abrir"] is True and j["placa"] == "ABC-123" and j["cajon"]
    with app.app_context():
        r = Reservation.query.filter_by(plate="ABC-123").one()
        assert r.status == "in" and r.source == "camara" and r.vehicle_type == "Automóvil"
    # la lectura ya se usó: un segundo carro no entra con la misma placa
    assert client.post("/api/entrada/vehiculo", headers=H).get_json()["motivo"] == "esperando_placa"


def test_entrada_lectura_caducada(client):
    registro.registrar_placa("ABC-123", "Automóvil")
    with app.app_context():
        CameraReading.query.update({"at": L.now() - timedelta(seconds=config.LECTURA_TTL + 5)})
        db.session.commit()
    assert client.post("/api/entrada/vehiculo", headers=H).get_json()["motivo"] == "esperando_placa"


def test_entrada_ya_dentro_no_vuelve_a_abrir(client):
    registro.registrar_placa("ABC-123", "Automóvil")
    assert client.post("/api/entrada/vehiculo", headers=H).get_json()["abrir"] is True
    registro.registrar_placa("ABC-123", "Automóvil")
    j = client.post("/api/entrada/vehiculo", headers=H).get_json()
    assert j["abrir"] is False and j["motivo"] == "inside"


def test_salida_sin_placa_o_sin_uid(client):
    assert client.post("/api/salida/nfc", json={"uid": "04A1B2C3"}, headers=H).get_json()["motivo"] == "sin_placa"
    assert client.post("/api/salida/nfc", json={}, headers=H).status_code == 400


def test_salida_cobra_y_autoriza(client):
    registro.registrar_placa("ABC-123", "Automóvil")
    client.post("/api/entrada/vehiculo", headers=H)
    assert registro.consultar_salida("ABC-123")[0] == "pay"  # la cámara de salida lee la placa
    j = client.post("/api/salida/nfc", json={"uid": "04A1B2C3"}, headers=H).get_json()
    assert j["autorizado"] is True and j["placa"] == "ABC-123" and j["cobrado"] == config.RATE
    with app.app_context():
        r = Reservation.query.filter_by(plate="ABC-123").one()
        assert r.status == "done" and L.paid_of(r) == config.RATE
    # con la misma tarjeta otra vez no pasa nada: la lectura ya se usó
    assert client.post("/api/salida/nfc", json={"uid": "04A1B2C3"}, headers=H).get_json()["motivo"] == "sin_placa"


def test_salida_pagada_en_linea_no_cobra_dos_veces(client):
    registro.registrar_placa("ABC-123", "Automóvil")
    client.post("/api/entrada/vehiculo", headers=H)
    with app.app_context():
        r = Reservation.query.filter_by(plate="ABC-123").one()
        L.add_payment(r, "tarjeta", ref=L.new_folio())
    registro.consultar_salida("ABC-123")
    j = client.post("/api/salida/nfc", json={"uid": "04A1B2C3"}, headers=H).get_json()
    assert j["autorizado"] is True and j["cobrado"] == 0


def test_salida_placa_que_no_esta_dentro(client):
    with app.app_context():
        db.session.add(CameraReading(side="salida", plate_norm="ZZZ999", at=L.now()))
        db.session.commit()
    j = client.post("/api/salida/nfc", json={"uid": "04A1B2C3"}, headers=H).get_json()
    assert j["autorizado"] is False and j["motivo"] == "notfound"


# ------------------------------------------------------------------ el sensor pide la lectura a la cámara
def test_entrada_pide_la_lectura_a_la_camara(client):
    assert registro.solicitud_pendiente("entrada") is False
    client.post("/api/entrada/vehiculo", json={"nuevo": True}, headers=H)
    assert registro.solicitud_pendiente("entrada") is True
    registro.cerrar_solicitud("entrada")
    assert registro.solicitud_pendiente("entrada") is False


def test_solicitud_caduca(client):
    from models import CameraRequest
    client.post("/api/entrada/vehiculo", json={"nuevo": True}, headers=H)
    with app.app_context():
        CameraRequest.query.update({"at": L.now() - timedelta(seconds=config.SOLICITUD_TTL + 5)})
        db.session.commit()
    assert registro.solicitud_pendiente("entrada") is False


def test_carro_nuevo_descarta_la_lectura_de_otro(client):
    registro.registrar_placa("ABC-123", "Automóvil")  # quedó una lectura de un carro que nunca llegó a la pluma
    j = client.post("/api/entrada/vehiculo", json={"nuevo": True}, headers=H).get_json()
    assert j["abrir"] is False and j["motivo"] == "esperando_placa"
    with app.app_context():
        assert CameraReading.query.count() == 0 and Reservation.query.count() == 0


def test_sin_nuevo_se_respeta_la_lectura(client):
    registro.registrar_placa("ABC-123", "Automóvil")
    assert client.post("/api/entrada/vehiculo", json={}, headers=H).get_json()["abrir"] is True


def test_salida_vehiculo_pide_lectura_y_avisa_si_ya_hay(client):
    j = client.post("/api/salida/vehiculo", json={"nuevo": True}, headers=H).get_json()
    assert j["lectura"] is False and registro.solicitud_pendiente("salida") is True
    registro.registrar_placa("ABC-123", "Automóvil")
    client.post("/api/entrada/vehiculo", json={}, headers=H)
    registro.consultar_salida("ABC-123")                      # la cámara de salida ya leyó
    assert client.post("/api/salida/vehiculo", json={}, headers=H).get_json()["lectura"] is True
    client.post("/api/salida/nfc", json={"uid": "04A1B2C3"}, headers=H)
    assert registro.solicitud_pendiente("salida") is False   # al usarse la lectura, no queda solicitud
