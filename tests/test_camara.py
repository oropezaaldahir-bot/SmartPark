"""Pruebas de la conexión cámara -> base de datos (con cámara, OCR y modelo simulados)."""
import os
import sys
import types
from datetime import timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import logic as L  # noqa: E402
from app import app  # noqa: E402
from models import Reservation, db  # noqa: E402
from modulos import registro  # noqa: E402
from modulos.placas import extraer_placa  # noqa: E402


@pytest.fixture()
def limpia():
    with app.app_context():
        db.drop_all()
        db.create_all()
        L.seed_demo()
    yield


def fila(placa):
    with app.app_context():
        return Reservation.query.filter(Reservation.plate == placa).first()


# ------------------------------------------------------------------ OCR -> placa (código tuyo, sin cambios)
@pytest.mark.parametrize("texto,placa,tipo", [
    ("EDOMEX PCH 96 04", "PCH9604", "Automóvil"),
    ("T PCH-96-04 EDOMEX", "PCH9604", "Automóvil"),
    ("Y123AB", "Y123AB", "Motocicleta"),
    ("AB12345", "AB12345", "Camión"),
    ("PCH 96O4", "PCH9604", "Automóvil"),  # O leída en lugar de 0
])
def test_extraer_placa(texto, placa, tipo):
    assert extraer_placa(texto) == (placa, tipo)


def test_extraer_placa_invalida():
    assert extraer_placa("MEXICO 2026") == (None, "Inválida")


# ------------------------------------------------------------------ registro en la base
def test_entrada_nueva_desde_camara(limpia):
    estado, msg = registro.registrar_entrada("PCH9604", "Automóvil")
    assert estado == "walkin" and "Entrada registrada" in msg and "SP-" in msg
    r = fila("PCH-9604")
    assert r.status == "in" and r.source == "camara" and r.vehicle_type == "Automóvil" and r.walkin
    # la misma placa otra vez: avisa que ya está dentro y NO duplica
    estado, msg = registro.registrar_entrada("PCH9604", "Automóvil")
    assert estado == "inside" and "Ya está dentro" in msg
    with app.app_context():
        assert Reservation.query.filter(Reservation.plate == "PCH-9604").count() == 1


def test_camara_confirma_reserva(limpia):
    with app.app_context():
        db.session.add(Reservation(code="SP-7777", plate="RES-4321", spot="F02", start=L.now() - timedelta(minutes=2),
                                   status="reserved", source="web"))
        db.session.commit()
    estado, msg = registro.registrar_entrada("RES4321", "Automóvil")
    assert estado == "checkin" and "F02" in msg
    r = fila("RES-4321")
    assert r.status == "in" and r.spot == "F02" and r.source == "web" and r.vehicle_type == "Automóvil"


def test_camara_reserva_muy_temprano(limpia):
    with app.app_context():
        db.session.add(Reservation(code="SP-7778", plate="TMP-1234", spot="F03", start=L.now() + timedelta(hours=3), status="reserved"))
        db.session.commit()
    estado, msg = registro.registrar_entrada("TMP1234", "Automóvil")
    assert estado == "early" and fila("TMP-1234").status == "reserved"


def test_estacionamiento_lleno(limpia):
    with app.app_context():
        occ = L.occupancy()
        for s, v in occ.items():
            if v == "free":
                db.session.add(Reservation(code=L.new_code(), plate="LLE-" + s, spot=s, start=L.now(), checkin=L.now(), status="in"))
        db.session.commit()
    assert registro.registrar_entrada("ZZZ9999", "Automóvil")[0] == "full"


def test_base_caida_no_rompe_la_camara(limpia, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("base caída")
    monkeypatch.setattr(L, "register_entry", boom)
    estado, msg = registro.registrar_entrada("PCH9604", "Automóvil")
    assert estado == "error" and "base de datos" in msg


def test_lo_registrado_por_la_camara_sale_en_el_panel_admin(limpia):
    registro.registrar_entrada("PCH9604", "Motocicleta")
    c = app.test_client()
    from admin import _LOCKS
    _LOCKS.clear()
    c.post("/admin/login", data={"usr": "admin", "pwd": "smartpark2026"})
    html = c.get("/admin/?q=pch9604").get_data(as_text=True)
    assert "PCH-9604" in html and "Cámara" in html and "Motocicleta" in html


# ------------------------------------------------------------------ main.py con cámara simulada
def _correr_main(monkeypatch, teclas, texto_ocr):
    """Ejecuta main.main() con cámara, OCR, YOLO y ventana simulados. Devuelve los 'estado' dibujados."""
    dibujos = []
    it = iter(teclas)

    cam = types.ModuleType("modulos.camara")
    cam.abrir_camara = lambda indice=1: ("cap", indice)
    cam.leer_frame = lambda cap: (True, "frame")
    cam.cerrar_camara = lambda cap: None
    ocr = types.ModuleType("modulos.ocr")
    ocr.iniciar_ocr = lambda: None
    ocr.detectar_texto = lambda r: None
    ocr.obtener_texto = lambda: texto_ocr
    det = types.ModuleType("modulos.detector_placa")
    det.detectar_zona_placa = lambda f: (10, 10, 100, 50)
    zona = types.ModuleType("modulos.zona_placa")
    zona.recortar_zona = lambda f, z: "recorte"
    ui = types.ModuleType("modulos.interfaz")
    ui.dibujar_frame = lambda frame, texto, zona=None, titulo="", estado="": dibujos.append((texto, estado))
    ui.leer_tecla = lambda: next(it)
    ui.es_detectar = lambda t: t == 32
    ui.es_confirmar = lambda t: t == 13
    ui.es_salir = lambda t: t in (113, 27)
    for n, m in (("camara", cam), ("ocr", ocr), ("detector_placa", det), ("zona_placa", zona), ("interfaz", ui)):
        monkeypatch.setitem(sys.modules, f"modulos.{n}", m)
        monkeypatch.setattr(sys.modules["modulos"], n, m, raising=False)
    sys.modules.pop("main", None)
    import main
    main.main()
    sys.modules.pop("main", None)
    return dibujos


def test_main_detectar_confirmar_y_guardar(limpia, monkeypatch):
    d = _correr_main(monkeypatch, [32, 13, 113], "EDOMEX PCH 96 04")
    assert ("PCH9604 - Automóvil", "ENTER = registrar entrada") in d   # tras ESPACIO pide confirmar
    r = fila("PCH-9604")
    assert r and r.status == "in" and r.source == "camara"
    assert "Entrada registrada" in d[-1][1] or any("Entrada registrada" in e for _, e in d)


def test_main_enter_sin_detectar_no_registra(limpia, monkeypatch):
    d = _correr_main(monkeypatch, [13, 113], "EDOMEX PCH 96 04")
    assert any("Primero detecta" in e for _, e in d)
    assert fila("PCH-9604") is None


def test_main_texto_ilegible_no_registra(limpia, monkeypatch):
    d = _correr_main(monkeypatch, [32, 13, 113], "MEXICO 2026")
    assert any(t == "Placa no reconocida" for t, _ in d)
    with app.app_context():
        assert Reservation.query.filter_by(source="camara").count() == 0


# ------------------------------------------------------------------ interfaz real (si hay OpenCV)
def test_interfaz_real(monkeypatch):
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    from modulos import interfaz
    mostrado = []
    monkeypatch.setattr(cv2, "imshow", lambda t, f: mostrado.append(f))
    interfaz.dibujar_frame(np.zeros((120, 400, 3), np.uint8), "ABC1234 - Automóvil", (5, 5, 50, 30), estado="Ya está dentro: cajón A01")
    assert mostrado and mostrado[0].any()  # se dibujó texto
    assert interfaz.es_confirmar(13) and not interfaz.es_confirmar(32) and interfaz.es_detectar(32)


# ------------------------------------------------------------------ migración de una base creada antes
def test_migracion_agrega_columnas(tmp_path):
    import sqlite3
    import subprocess
    dbf = tmp_path / "vieja.db"
    con = sqlite3.connect(dbf)
    con.executescript("""CREATE TABLE reservaciones (code VARCHAR(10) PRIMARY KEY, plate VARCHAR(10) NOT NULL, spot VARCHAR(3) NOT NULL,
        start TIMESTAMP NOT NULL, checkin TIMESTAMP, exit_at TIMESTAMP, status VARCHAR(10) NOT NULL, hold_until TIMESTAMP,
        walkin BOOLEAN NOT NULL DEFAULT 0, fee_amount INTEGER, fee_at TIMESTAMP, fee_method VARCHAR(10), fee_ref VARCHAR(20));
        INSERT INTO reservaciones (code,plate,spot,start,status) VALUES ('SP-0001','OLD-111','A01','2026-01-01 10:00:00','done');""")
    con.commit(); con.close()
    code = ("import os,sys;sys.path.insert(0,%r);os.environ['DATABASE_URL']='sqlite:///%s';os.environ['SEED_DEMO']='0';"
            "from app import app;from models import Reservation;"
            "ctx=app.app_context();ctx.push();"
            "import logic as L;print(L.register_entry('NEW1234',source='camara',vehicle_type='Automóvil')['status']);"
            "print(Reservation.query.get('SP-0001').plate)") % (ROOT, str(dbf).replace("\\", "/"))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["walkin", "OLD-111"]  # la fila vieja sigue y las columnas nuevas funcionan
