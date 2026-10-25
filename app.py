"""app.py · SmartPark (servidor Flask). Ejecuta con:  python app.py
Antes era JavaScript en el navegador; ahora toda la lógica corre en Python y los datos
viven en una base SQL."""
import math
from datetime import datetime, timedelta

from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for

import config
import logic as L
from admin import bp as admin_bp
from models import Reservation, db
from pasarela import bp as pasarela_bp, start_checkout
from ticket_png import build as build_png

app = Flask(__name__)
app.config.update(
    SECRET_KEY=config.SECRET_KEY,
    SQLALCHEMY_DATABASE_URI=config.DATABASE_URL,
    SESSION_COOKIE_SAMESITE="Lax",  # evita que otros sitios envíen formularios con tu sesión
    SESSION_COOKIE_HTTPONLY=True,
)
db.init_app(app)
app.register_blueprint(pasarela_bp)
app.register_blueprint(admin_bp)

def ensure_columns():
    """Agrega las columnas nuevas si la base ya existía (create_all no modifica tablas)."""
    from sqlalchemy import inspect, text
    cols = {c["name"] for c in inspect(db.engine).get_columns("reservaciones")}
    add = "ADD" if db.engine.dialect.name == "mssql" else "ADD COLUMN"
    for name, ddl in (("vehicle_type", "VARCHAR(12)"), ("source", "VARCHAR(10)")):
        if name not in cols:
            db.session.execute(text(f"ALTER TABLE reservaciones {add} {name} {ddl}"))
    db.session.commit()


with app.app_context():
    db.create_all()
    ensure_columns()
    if config.SEED_DEMO:
        L.seed_demo()

LOGO = (
    '<svg width="28" height="28" viewBox="0 0 34 34" fill="none" stroke="#111" stroke-width="3" '
    'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l3-6h18l3 6"/><path d="M6 12h22v16H6z"/>'
    '<path d="M11 28v-7h12v7"/><path d="M14 17h6"/></svg>'
)
TABS = [
    ("entrada", "acceso", "Entrada", '<path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5"/><path d="M14 8l4 4-4 4M18 12H8"/>'),
    ("reservar", "reservar", "Reservar", '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>'),
    ("boleto", "boleto", "Mi boleto", '<path d="M3 9a2 2 0 0 0 0 6v3h18v-3a2 2 0 0 1 0-6V6H3z"/><path d="M14 6v12" stroke-dasharray="2 2"/>'),
]


@app.context_processor
def inject():
    return dict(
        AREAS=config.AREAS, RATE=config.RATE, LOGO=LOGO, TABS=TABS,
        money=L.money, hhmm=L.hhmm, fmt_plate=L.fmt_plate, fmt_dur=L.fmt_dur, day_label=L.day_label,
    )


@app.get("/")
def index():
    return redirect(url_for("acceso"))


# ================================================================ ENTRADA
@app.route("/acceso", methods=["GET", "POST"])
def acceso():
    err, plate = "", ""
    if request.method == "POST":
        plate = L.fmt_plate(L.norm(request.form.get("placa"))[:7])
        res = L.register_entry(request.form.get("placa"), source="web", only_known=True)
        if res["status"] in ("inside", "checkin", "walkin"):
            session["last"] = res["r"].code
            extra = {"d": 1} if res["status"] == "inside" else {}
            return redirect(url_for("boleto", code=res["r"].code, **extra))
        err = res["msg"]
    return render_template("acceso.html", err=err, plate=plate, free=L.count_free())


# ================================================================ BOLETO
@app.get("/boleto")
@app.get("/boleto/<code>")
def boleto(code=None):
    code = code or session.get("last")
    r = db.session.get(Reservation, code) if code else None
    if not r or not r.checkin:
        return render_template("boleto.html", r=None)
    session["last"] = r.code
    paid, due = L.paid_of(r), L.due_of(r)
    done = r.status == "done"
    settled = paid > 0 and due == 0
    dup = request.args.get("d") == "1"
    if done:
        title, sub = "Salida registrada", "Gracias por visitarnos"
    elif settled:
        title, sub = "Pago registrado", "Ya puedes salir"
    elif dup:
        title, sub = "Ya estás dentro", "Este es tu boleto digital"
    else:
        title, sub = "¡Ingreso exitoso!", "Conserva este boleto digital"
    until = L.grace_until(r)
    return render_template(
        "boleto.html", r=r, paid=paid, due=due, done=done, settled=settled, title=title, sub=sub,
        pill=("SALIDA", "out") if done else ("PAGADO", "paid") if settled else ("ENTRADA", ""),
        dur=L.fmt_dur((r.exit_at or L.now()) - r.checkin), entry=L.clock_label(r.checkin),
        spot_lbl=f"{r.spot[0]}-{r.spot[1:]}", emp=L.is_emp(r.plate), barcode=L.barcode_svg(r.code),
        until=until, show_paid=done or settled,
    )


@app.post("/boleto/<code>/pagar")
def boleto_pagar(code):
    r = db.session.get(Reservation, code)
    if not r or not r.checkin:
        abort(404)
    due = L.due_of(r)
    if due <= 0:
        return redirect(url_for("boleto", code=code))
    return start_checkout("ticket", due, f"Estacionamiento · boleto {r.code}",
                          url_for("boleto", code=r.code), r.code)


@app.get("/boleto/<code>/ticket.png")
def boleto_png(code):
    r = db.session.get(Reservation, code)
    if not r or not r.checkin:
        abort(404)
    buf, name = build_png(r)
    return send_file(buf, mimetype="image/png", as_attachment=True, download_name=name)


# ================================================================ RESERVAR
def _parse_start(date, time):
    try:
        return datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _default_start():
    d = L.now() + timedelta(minutes=15)
    d = d.replace(second=0, microsecond=0)
    q = math.ceil(d.minute / 15) * 15
    return (d.replace(minute=0) + timedelta(minutes=q)) if q else d


def _form_state(values):
    """Lee los campos del formulario de reserva y calcula qué falta."""
    d0 = _default_start()
    plate = values.get("placa", "")
    date = values.get("fecha") or d0.strftime("%Y-%m-%d")
    time = values.get("hora") or d0.strftime("%H:%M")
    area = values.get("area") or values.get("area_cur")  # el botón pulsado gana sobre el área actual
    area = area if area in [a["id"] for a in config.AREAS] else None
    spot = values.get("spot") or values.get("sel") or None
    if not area or not spot or spot[0] != area:
        spot = None
    occ = L.occupancy()
    if spot and occ.get(spot) != "free":
        spot = None
    start = _parse_start(date, time)
    ok_time = bool(start) and start + config.TOL >= L.now()
    ok_plate = len(L.norm(plate)) >= 5
    missing = []
    if not ok_plate:
        missing.append("placa")
    if not ok_time:
        missing.append("hora de llegada")
    if not area:
        missing.append("área")
    elif not spot:
        missing.append("cajón")
    return dict(plate=plate, date=date, time=time, area=area, spot=spot, start=start, occ=occ,
                missing=missing, steps=[ok_plate and ok_time, bool(area), bool(spot)])


def _render_form(values, error=None):
    s = _form_state(values)
    fee = L.reservation_fee(s["start"]) if s["start"] else None
    grid = L.area_grid(s["area"], s["occ"], s["spot"]) if s["area"] else None
    cur = next((i for i, v in enumerate(s["steps"]) if not v), 3)
    return render_template(
        "reservaciones.html", mode="form", s=s, fee=fee, grid=grid, area_obj=L.area_by_id(s["area"]) if s["area"] else None,
        free=L.free_by_area(s["occ"]), today=L.now().strftime("%Y-%m-%d"), cur=cur,
        error=error or ("Falta: " + ", ".join(s["missing"]) + "." if s["missing"] else "Todo listo para reservar."),
        ok=not s["missing"],
    )


@app.route("/reservar", methods=["GET", "POST"])
def reservar():
    r = db.session.get(Reservation, session["mine"]) if session.get("mine") else None
    if session.get("mine") and not r:
        session.pop("mine", None)
    if r and r.status != "hold":
        return _render_ticket(r)

    if request.method == "POST":  # botón "Ir a pagar"
        s = _form_state(request.form)
        if s["missing"]:
            return _render_form(request.form, "Falta: " + ", ".join(s["missing"]) + ".")
        if L.occupancy().get(s["spot"]) != "free":
            return _render_form(request.form, "Ese cajón acaba de ocuparse. Elige otro.")
        fee = L.reservation_fee(s["start"])
        # El cajón se aparta 10 min mientras se paga en la pasarela
        rec = Reservation(code=L.new_code(), plate=L.fmt_plate(s["plate"]), spot=s["spot"], start=s["start"],
                          status="hold", hold_until=L.now() + config.HOLD)
        db.session.add(rec)
        db.session.commit()
        return start_checkout("reservation", fee["amount"], f"Reservación cajón {rec.spot} · {fee['label']}",
                              url_for("reservar"), rec.code)
    return _render_form(request.args)


def _render_ticket(r):
    L.mark_expired(r)
    a = L.area_by_id(r.spot[0])
    cls, txt = L.ticket_status(r)
    inside = r.status == "in"
    dead = r.status in ("expired", "cancelled", "done")
    due = L.due_of(r) if inside else 0
    occ = L.occupancy()
    return render_template(
        "reservaciones.html", mode="ticket", r=r, a=a, cls=cls, txt=txt, inside=inside, dead=dead, due=due,
        paid=L.paid_of(r), grid=L.area_grid(a["id"], occ, r.spot, interactive=False),
    )


@app.post("/reservar/cancelar")
def reservar_cancelar():
    r = db.session.get(Reservation, session.get("mine") or "")
    if not r:
        return redirect(url_for("reservar"))
    if r.status == "in":
        if L.due_of(r) > 0:
            return redirect(url_for("boleto", code=r.code))
        L.do_exit(r)
        flash("Salida registrada. ¡Gracias por tu visita!", "ok")
    else:
        r.status = "cancelled"
        db.session.commit()
        flash("Reserva cancelada. El cajón quedó libre.", "ok")
    session.pop("mine", None)
    return redirect(url_for("reservar"))


@app.post("/reservar/nueva")
def reservar_nueva():
    session.pop("mine", None)
    return redirect(url_for("reservar"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
