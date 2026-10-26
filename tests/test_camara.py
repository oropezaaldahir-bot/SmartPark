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
from models import Plate, Reservation, db  # noqa: E402
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


# ------------------------------------------------------------------ guardar placas en la base
def placa(norm_):
    with app.app_context():
        return Plate.query.filter_by(plate_norm=norm_).first()


def test_camara_guarda_placa_nueva(limpia):
    estado, msg = registro.registrar_placa("PCH9604", "Automóvil")
    assert estado == "new" and "guardada" in msg
    p = placa("PCH9604")
    assert p.plate == "PCH-9604" and p.vehicle_type == "Automóvil" and p.hits == 1
    # la cámara NO abre boleto: la entrada se hace después en /acceso
    with app.app_context():
        assert Reservation.query.filter(Reservation.plate == "PCH-9604").count() == 0


def test_camara_misma_placa_no_duplica(limpia):
    registro.registrar_placa("PCH9604", "Automóvil")
    estado, msg = registro.registrar_placa("pch 96-04", "Automóvil")
    assert estado == "known" and "ya estaba" in msg
    with app.app_context():
        assert Plate.query.count() == 1 and placa("PCH9604").hits == 2


def test_placa_guardada_por_camara_puede_entrar_por_acceso(limpia):
    c = app.test_client()
    assert "Placa no registrada" in c.post("/acceso", data={"placa": "PCH9604"}).get_data(as_text=True)
    registro.registrar_placa("PCH9604", "Automóvil")
    r = c.post("/acceso", data={"placa": "PCH9604"})
    assert r.status_code == 302
    with app.app_context():
        w = Reservation.query.filter_by(plate="PCH-9604").one()
        assert w.status == "in" and w.source == "web"


def test_placa_incompleta_no_se_guarda(limpia):
    assert registro.registrar_placa("AB", "Automóvil")[0] == "invalid"
    with app.app_context():
        assert Plate.query.count() == 0


def test_base_caida_no_rompe_la_camara(limpia, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("base caída")
    monkeypatch.setattr(L, "save_plate", boom)
    estado, msg = registro.registrar_placa("PCH9604", "Automóvil")
    assert estado == "error" and "base de datos" in msg


def test_register_entry_conserva_reglas_de_reserva(limpia):
    """La lógica de reservas sigue igual (sin only_known, como la usa el admin)."""
    with app.app_context():
        db.session.add(Reservation(code="SP-7777", plate="RES-4321", spot="F02", start=L.now() - timedelta(minutes=2),
                                   status="reserved", source="web"))
        db.session.add(Reservation(code="SP-7778", plate="TMP-1234", spot="F03", start=L.now() + timedelta(hours=3), status="reserved"))
        db.session.commit()
        assert L.register_entry("RES4321", "web", "Automóvil", only_known=True)["status"] == "checkin"
        assert L.register_entry("TMP1234", "web", only_known=True)["status"] == "early"
        assert L.register_entry("ZZZ9999", "web", only_known=True)["status"] == "unknown"
        assert L.register_entry("ZZZ9999")["status"] == "walkin"


# ------------------------------------------------------------------ main.py con cámara simulada
def _correr_main(monkeypatch, teclas, texto_ocr, modo="entrada"):
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
    ui.dibujar_frame = lambda frame, texto, zona=None, titulo="", estado="", ayuda="": dibujos.append((texto, estado))
    ui.leer_tecla = lambda: next(it)
    ui.es_detectar = lambda t: t == 32
    ui.es_confirmar = lambda t: t == 13
    ui.es_salir = lambda t: t in (113, 27)
    for n, m in (("camara", cam), ("ocr", ocr), ("detector_placa", det), ("zona_placa", zona), ("interfaz", ui)):
        monkeypatch.setitem(sys.modules, f"modulos.{n}", m)
        monkeypatch.setattr(sys.modules["modulos"], n, m, raising=False)
    sys.modules.pop("main", None)
    import main
    main.main(modo)
    sys.modules.pop("main", None)
    return dibujos


def test_main_detectar_confirmar_y_guardar(limpia, monkeypatch):
    d = _correr_main(monkeypatch, [32, 13, 113], "EDOMEX PCH 96 04")
    assert ("PCH9604 - Automóvil", "ENTER = guardar placa") in d   # tras ESPACIO pide confirmar
    p = placa("PCH9604")
    assert p and p.vehicle_type == "Automóvil"
    assert any("guardada" in e for _, e in d)


def test_main_enter_sin_detectar_no_registra(limpia, monkeypatch):
    d = _correr_main(monkeypatch, [13, 113], "EDOMEX PCH 96 04")
    assert any("Primero detecta" in e for _, e in d)
    assert placa("PCH9604") is None


def test_main_texto_ilegible_no_registra(limpia, monkeypatch):
    d = _correr_main(monkeypatch, [32, 13, 113], "MEXICO 2026")
    assert any(t == "Placa no reconocida" for t, _ in d)
    with app.app_context():
        assert Plate.query.count() == 0


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
            "import logic as L;print(L.register_entry('NEW1234',source='web',vehicle_type='Automóvil')['status']);"
            "print(Reservation.query.get('SP-0001').plate)") % (ROOT, str(dbf).replace("\\", "/"))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["walkin", "OLD-111"]  # la fila vieja sigue y las columnas nuevas funcionan


# ------------------------------------------------------------------ cámara de SALIDA
def _dentro(placa="SAL1234", minutos=70):
    """Un vehículo que entró hace `minutos` y su placa guardada por la cámara de entrada."""
    with app.app_context():
        t = L.now() - timedelta(minutes=minutos)
        r = Reservation(code="SP-5001", plate=L.fmt_plate(placa), spot="D02", start=t, checkin=t, status="in", walkin=True)
        db.session.add(r)
        db.session.commit()
        L.save_plate(placa, "Automóvil")


def test_salida_busca_tarifa_y_no_deja_salir_sin_pagar(limpia):
    _dentro(minutos=70)  # 70 min -> 2 horas iniciadas = $30
    estado, msg = registro.consultar_salida("SAL1234")
    assert estado == "pay" and "$30" in msg and "SP-5001" in msg
    estado, msg = registro.registrar_salida("SAL1234")
    assert estado == "pay" and "NO puede salir" in msg
    with app.app_context():
        assert db.session.get(Reservation, "SP-5001").status == "in"
        assert Plate.query.filter_by(plate_norm="SAL1234").count() == 1   # la placa sigue guardada


def test_salida_pagada_deja_salir_y_borra_la_placa(limpia):
    _dentro(minutos=70)
    with app.app_context():
        L.add_payment(db.session.get(Reservation, "SP-5001"), "tarjeta", "PG-ABC123")
    assert registro.consultar_salida("SAL 1234")[0] == "ok"
    estado, msg = registro.registrar_salida("SAL1234")
    assert estado == "exit" and "Placa eliminada" in msg
    with app.app_context():
        r = db.session.get(Reservation, "SP-5001")
        assert r.status == "done" and r.exit_at and len(r.payments) == 1       # historial y pago se conservan
        assert Plate.query.filter_by(plate_norm="SAL1234").count() == 0         # placa borrada
    # sin su placa guardada ya no puede volver a entrar por /acceso hasta que la cámara la guarde otra vez
    assert "Placa no registrada" in app.test_client().post("/acceso", data={"placa": "SAL1234"}).get_data(as_text=True)
    # y si intenta salir otra vez, ya no está dentro
    assert registro.registrar_salida("SAL1234")[0] == "notfound"


def test_salida_placa_desconocida_o_incompleta(limpia):
    assert registro.consultar_salida("ZZZ9999")[0] == "notfound"
    assert registro.registrar_salida("AB")[0] == "invalid"


def test_main_salida_cobra_y_deja_salir(limpia, monkeypatch):
    _dentro(placa="PCH9604", minutos=30)
    # ESPACIO (consulta tarifa) -> ENTER (debe pagar) -> se paga -> ENTER otra vez (sale) -> q
    pagado = {"hecho": False}
    orig = registro.registrar_salida

    def registrar(placa):  # el pago ocurre justo después del primer intento sin pagar
        r = orig(placa)
        if r[0] == "pay" and not pagado["hecho"]:
            with app.app_context():
                L.add_payment(db.session.get(Reservation, "SP-5001"), "efectivo")
            pagado["hecho"] = True
        return r
    monkeypatch.setattr(registro, "registrar_salida", registrar)
    d = _correr_main(monkeypatch, [32, 13, 13, 113], "EDOMEX PCH 96 04", modo="salida")
    estados = [e for _, e in d]
    assert any("Debe pagar $15" in e for e in estados)           # al detectar muestra la tarifa
    assert any("NO puede salir" in e for e in estados)           # primer ENTER sin pagar
    assert any("Placa eliminada" in e for e in estados)          # segundo ENTER ya pagado
    with app.app_context():
        assert db.session.get(Reservation, "SP-5001").status == "done"
        assert Plate.query.filter_by(plate_norm="PCH9604").count() == 0


def test_salida_desde_admin_tambien_borra_la_placa(limpia):
    _dentro(minutos=10)
    with app.app_context():
        L.do_exit(db.session.get(Reservation, "SP-5001"))
        assert Plate.query.filter_by(plate_norm="SAL1234").count() == 0
