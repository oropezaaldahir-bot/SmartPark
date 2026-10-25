"""Pruebas de SmartPark. Ejecuta con:  python -m pytest -q"""
import os
import re
import sys
from datetime import timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["DEMO_PAGOS"] = "1"

import logic as L  # noqa: E402
from app import app  # noqa: E402
from models import Employee, Reservation, db  # noqa: E402

GOOD = {"cc": "4242 4242 4242 4242", "exp": "12/35", "cvv": "123"}


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.app_context():
        db.drop_all()
        db.create_all()
        L.seed_demo()
        for p in ("XYZ1234", "GAT5678", "CAN4444"):  # placas que la cámara ya guardó
            L.save_plate(p, "Automóvil")
    with app.test_client() as c:
        yield c


def rec(code):
    with app.app_context():
        return db.session.get(Reservation, code)


def pay_ok(c):
    r = c.post("/pasarela/", data=dict(GOOD, pagar="1"))
    assert "Pago aprobado" in r.get_data(as_text=True)
    return r


def test_tarifas():
    from datetime import datetime
    f = lambda y, m, d, h: L.reservation_fee(datetime(y, m, d, h)).get("amount")
    assert f(2026, 10, 26, 8) == 30   # lunes pico
    assert f(2026, 10, 26, 13) == 20  # base
    assert f(2026, 10, 30, 20) == 40  # viernes noche
    assert f(2026, 10, 31, 12) == 35  # sábado día
    assert f(2026, 10, 28, 3) == 15   # madrugada


def test_isemp_ignora_guiones(client):
    with app.app_context():
        db.session.add(Employee(name="Ana", plate="ABC-123", plate_norm="ABC123"))
        db.session.commit()
        assert L.is_emp("abc 123") and L.is_emp("ABC-123") and not L.is_emp("ZZZ999")


def test_entrada_boleto_y_pago_por_pasarela(client):
    r = client.post("/acceso", data={"placa": "xyz1234"}, follow_redirects=False)
    assert r.status_code == 302
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "XYZ-1234" in page and "$15" in page and "Pagar en línea" in page and "<svg viewBox" in page
    code = re.search(r"SP-\d{4}", page).group()

    r = client.post(f"/boleto/{code}/pagar")
    assert r.headers["Location"].endswith("/pasarela/")
    g = client.get("/pasarela/").get_data(as_text=True)
    assert "$15 MXN" in g and "SIMULACIÓN" in g

    # tarjeta inválida: no cobra y no repite el número en la respuesta
    bad = client.post("/pasarela/", data={"cc": "1234 5678 9012 3456", "exp": "12/35", "cvv": "123", "pagar": "1"})
    t = bad.get_data(as_text=True)
    assert "Revisa el número" in t and "1234 5678" not in t
    pay_ok(client)

    page = client.get(f"/boleto/{code}").get_data(as_text=True)
    assert "PAGADO" in page and "Pago registrado" in page
    with app.app_context():
        r = db.session.get(Reservation, code)
        assert len(r.payments) == 1 and r.payments[0].method == "tarjeta" and r.payments[0].ref.startswith("PG-")
    # recargar la pasarela no cobra dos veces
    assert "No hay un pago pendiente" in client.get("/pasarela/").get_data(as_text=True)


def test_no_se_guardan_datos_de_tarjeta(client):
    r = client.post("/acceso", data={"placa": "GAT5678"})
    code = re.search(r"SP-\d{4}", r.headers["Location"]).group()
    client.post(f"/boleto/{code}/pagar")
    pay_ok(client)
    import sqlite3  # volcado de TODA la base y de la cookie de sesión
    with app.app_context():
        dump = " ".join(str(v) for tbl in (Reservation,) for row in tbl.query.all() for v in vars(row).values())
        pays = " ".join(str(vars(p)) for row in Reservation.query.all() for p in row.payments)
    cookie = " ".join(str(c) for c in client._cookies.values()) if hasattr(client, "_cookies") else ""
    for secreto in ("4242", "424242424242", "'cvv'"):
        assert secreto not in dump + pays + cookie


def test_pasarela_cancelar_y_vencida(client):
    r = client.post("/acceso", data={"placa": "CAN4444"})
    code = re.search(r"SP-\d{4}", r.headers["Location"]).group()
    client.post(f"/boleto/{code}/pagar")
    r = client.post("/pasarela/", data={"cancelar": "1"})
    assert r.status_code == 302
    assert "ENTRADA" in client.get(f"/boleto/{code}").get_data(as_text=True)
    client.post(f"/boleto/{code}/pagar")
    with client.session_transaction() as s:
        c = dict(s["checkout"])
        c["expires"] = (L.now() - timedelta(minutes=1)).isoformat()
        s["checkout"] = c
    assert client.get("/pasarela/").status_code == 302


def test_reservar_con_pago_y_hold(client):
    q = dict(placa="res 4321", fecha=(L.now() + timedelta(days=3)).strftime("%Y-%m-%d"), hora="20:00", area="F", spot="F01")
    page = client.get("/reservar", query_string=q).get_data(as_text=True)
    assert "Ir a pagar" in page and "Todo listo" in page
    r = client.post("/reservar", data=q)
    assert r.headers["Location"].endswith("/pasarela/")
    with app.app_context():
        hold = Reservation.query.filter_by(plate="RES-4321").one()
        assert hold.status == "hold"
        assert L.occupancy()["F01"] == "resv"  # apartado mientras se paga
    pay_ok(client)
    with app.app_context():
        r = Reservation.query.filter_by(plate="RES-4321").one()
        assert r.status == "reserved" and r.fee_method == "tarjeta" and r.fee_ref.startswith("PG-") and r.hold_until is None
        assert r.fee_amount == L.reservation_fee(r.start)["amount"]
    t = client.get("/reservar").get_data(as_text=True)
    assert "pagada" in t and "F01" in t


def test_reservar_cancelar_pago_libera_cajon(client):
    q = dict(placa="LIB 1234", fecha=(L.now() + timedelta(days=2)).strftime("%Y-%m-%d"), hora="12:00", area="E", spot="E05")
    client.post("/reservar", data=q)
    client.post("/pasarela/", data={"cancelar": "1"})
    with app.app_context():
        assert Reservation.query.filter_by(plate="LIB-1234").count() == 0
        assert L.occupancy()["E05"] == "free"


def test_reservar_valida_faltantes(client):
    r = client.post("/reservar", data={"placa": "ab"})
    t = r.get_data(as_text=True)
    assert "Falta: placa" in t and "área" in t


def test_admin_login_bloqueo_y_acceso(client):
    assert client.get("/admin/").status_code == 302  # sin sesión
    for i in range(2):
        t = client.post("/admin/login", data={"usr": "admin", "pwd": "mala"}).get_data(as_text=True)
        assert "Intentos restantes" in t
    t = client.post("/admin/login", data={"usr": "admin", "pwd": "mala"}).get_data(as_text=True)
    assert "Demasiados intentos" in t
    t = client.post("/admin/login", data={"usr": "admin", "pwd": "smartpark2026"}).get_data(as_text=True)
    assert "Demasiados intentos" in t  # sigue bloqueado aunque la clave sea correcta
    from admin import _LOCKS
    _LOCKS.clear()
    r = client.post("/admin/login", data={"usr": "admin", "pwd": "smartpark2026"})
    assert r.status_code == 302
    assert client.get("/admin/").status_code == 200


def login(c):
    from admin import _LOCKS
    _LOCKS.clear()
    c.post("/admin/login", data={"usr": "admin", "pwd": "smartpark2026"})


def test_admin_panel_cobro_y_reservas(client):
    login(client)
    with app.app_context():  # DEMO7 lleva 2 h y 5 min dentro -> 3 horas iniciadas
        r7 = db.session.get(Reservation, "SP-0007")
        r7.checkin = L.now() - timedelta(minutes=125)
        db.session.commit()
    html = client.get("/admin/").get_data(as_text=True)
    assert html.count('class="kpi ') == 5 and "DEMO7" in html and "<script" not in html
    assert "$45 por cobrar" in html  # DEMO7: 2 h + minutos = 3 h iniciadas

    # buscar
    assert "DEMO2" in client.get("/admin/?q=demo2").get_data(as_text=True)
    assert "DEMO7" not in client.get("/admin/?q=demo2").get_data(as_text=True)

    # cobrar y salir
    c = client.get("/admin/confirmar/out?code=SP-0007").get_data(as_text=True)
    assert "$45 MXN" in c and "efectivo" in c
    client.post("/admin/accion/out", data={"code": "SP-0007"})
    r = rec("SP-0007")
    with app.app_context():
        r = db.session.get(Reservation, "SP-0007")
        assert r.status == "done" and r.payments[0].method == "efectivo" and r.payments[0].amount == 45
    # doble salida: avisa que ya cambió
    client.post("/admin/accion/out", data={"code": "SP-0007"})
    assert "ya cambió" in client.get("/admin/").get_data(as_text=True)

    # reservar desde el mapa (cobro en efectivo)
    html = client.get("/admin/?area=F&spot=F01&placa=adm 9876").get_data(as_text=True)
    assert "Cobrar $" in html
    assert "Tarifa de reservación" in client.get("/admin/confirmar/reservar?spot=F01&placa=adm 9876").get_data(as_text=True)
    client.post("/admin/accion/reservar", data={"spot": "F01", "placa": "adm 9876"})
    with app.app_context():
        r = Reservation.query.filter_by(plate="ADM-9876").one()
        assert r.fee_method == "efectivo" and r.status == "reserved"
    assert "$" in client.get("/admin/").get_data(as_text=True)

    # empleados (placa duplicada con otro formato)
    client.post("/admin/empleados", data={"nombre": "Ana", "placa": "zzz 111"})
    client.post("/admin/empleados", data={"nombre": "Otra", "placa": "ZZZ-111"}, follow_redirects=True)
    with app.app_context():
        assert Employee.query.count() == 1
    client.post("/admin/accion/empdel", data={"id": 1})
    with app.app_context():
        assert Employee.query.count() == 0

    # cerrar sesión
    client.post("/admin/accion/salir")
    assert client.get("/admin/").status_code == 302


def test_ticket_png(client):
    r = client.get("/boleto/SP-0001/ticket.png")
    assert r.status_code == 200 and r.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_sin_javascript():
    for f in os.listdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", f), encoding="utf-8").read()
        assert "<script" not in src.lower() and "onclick" not in src.lower(), f


def test_clic_en_cajon_conserva_area_y_datos(client):
    """Simula lo que envía el navegador al pulsar un cajón (solo viaja el botón pulsado)."""
    f = (L.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    t = client.get("/reservar", query_string=dict(placa="pnk 123", fecha=f, hora="20:00", sel="", area_cur="F", spot="F02")).get_data(as_text=True)
    assert "Todo listo" in t and 'name="sel" value="F02"' in t
    # al cambiar de área con un cajón elegido, el cajón anterior se descarta
    t = client.get("/reservar", query_string=dict(placa="pnk 123", fecha=f, hora="20:00", sel="F02", area_cur="F", area="B")).get_data(as_text=True)
    assert "Falta: cajón" in t
    login(client)
    h = client.get("/admin/", query_string=dict(area_cur="F", sel="", placa="x", spot="F03")).get_data(as_text=True)
    assert "Cajón F03" in h


def test_admin_confirmar_reserva_usa_cajon_elegido(client):
    login(client)
    c = client.get("/admin/confirmar/reservar", query_string=dict(sel="F03", placa="adm 9876", area_cur="F")).get_data(as_text=True)
    assert "F03" in c and "ADM-9876" in c and 'name="spot" value="F03"' in c


def test_acceso_solo_placas_guardadas(client):
    # placa que la cámara nunca vio: no entra y no se crea ningún boleto
    r = client.post("/acceso", data={"placa": "NUE9999"})
    assert r.status_code == 200 and "Placa no registrada" in r.get_data(as_text=True)
    with app.app_context():
        assert Reservation.query.filter_by(plate="NUE-9999").count() == 0
    # la cámara la guarda -> ahora sí entra
    with app.app_context():
        assert L.save_plate("nue 9999", "Automóvil")[0] == "new"
    r = client.post("/acceso", data={"placa": "NUE9999"})
    assert r.status_code == 302
    with app.app_context():
        assert Reservation.query.filter_by(plate="NUE-9999", status="in").count() == 1


def test_acceso_permite_reserva_y_empleado(client):
    with app.app_context():
        db.session.add(Employee(name="Ana", plate="EMP-001", plate_norm="EMP001"))
        db.session.commit()
    assert client.post("/acceso", data={"placa": "emp 001"}).status_code == 302   # empleado
    assert client.post("/acceso", data={"placa": "DEMO3"}).status_code == 200      # reserva demo: aún es temprano
    with app.app_context():
        assert L.plate_known("demo3") and not L.plate_known("QQQ1111")


def test_grafica_cuenta_entradas_reales_por_dia(client):
    from datetime import timedelta
    with app.app_context():
        antes = [v for _, v in L.entries_by_day(7)]
        assert len(antes) == 7 and antes[-1] == 4  # hoy: las 4 DEMO que ya entraron
        # un carro más hoy y dos hace 2 días: sube solo la barra de ese día
        for code, dias in (("SP-9001", 0), ("SP-9002", 2), ("SP-9003", 2)):
            t = L.now() - timedelta(days=dias, minutes=5)
            db.session.add(Reservation(code=code, plate=code, spot="D01", start=t, checkin=t, status="done"))
        db.session.commit()
        despues = [v for _, v in L.entries_by_day(7)]
        assert despues[-1] == antes[-1] + 1 and despues[-3] == antes[-3] + 2
        assert sum(despues) == sum(antes) + 3
        # los que entran por la web también cuentan
    client.post("/acceso", data={"placa": "XYZ1234"})
    with app.app_context():
        assert L.entries_by_day(7)[-1][1] == despues[-1] + 1
    login(client)
    html = client.get("/admin/").get_data(as_text=True)
    assert "últimos 7 días" in html and "entradas</title>" in html
