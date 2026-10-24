"""admin.py · Panel de administrador y su login.
La contraseña vive en el servidor (config.py / variables de entorno) y la sesión la firma
Flask, así que ya no se puede "saltar" el login desde la consola del navegador."""
import hmac
from datetime import timedelta
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape
from werkzeug.security import check_password_hash

import logic as L
from config import ADMIN_PASS, ADMIN_PASS_HASH, ADMIN_USER, AREAS, LOCK_SECONDS, MAX_TRIES
from models import Employee, Payment, Reservation, db

bp = Blueprint("admin", __name__, url_prefix="/admin")

_LOCKS = {}  # ip -> {"tries": n, "until": datetime}  (en memoria; en producción usa Redis o la base)


def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"):
            return redirect(url_for("admin.login"))
        return f(*a, **k)

    return w


def _pass_ok(p):
    if ADMIN_PASS_HASH:
        return check_password_hash(ADMIN_PASS_HASH, p)
    return hmac.compare_digest(p.encode(), ADMIN_PASS.encode())


# ---------------------------------------------------------------- login
@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin"):
        return redirect(url_for("admin.panel"))
    ip = request.remote_addr or "?"
    lock = _LOCKS.setdefault(ip, {"tries": 0, "until": None})
    n = L.now()
    if lock["until"] and n >= lock["until"]:
        lock.update(tries=0, until=None)
    locked = bool(lock["until"])
    msg, bad = "", ""
    if locked:
        left = max(1, int((lock["until"] - n).total_seconds()))
        msg = f"Demasiados intentos. Espera {left} s para volver a intentar."
    elif request.method == "POST":
        u = (request.form.get("usr") or "").strip()
        p = request.form.get("pwd") or ""
        if not u or not p:
            msg, bad = "Escribe tu usuario y tu contraseña.", ("u" if not u else "p")
        elif u.lower() == ADMIN_USER.lower() and _pass_ok(p):
            lock.update(tries=0, until=None)
            session["admin"] = True
            return redirect(url_for("admin.panel"))
        else:
            lock["tries"] += 1
            if lock["tries"] >= MAX_TRIES:
                lock["until"] = n + timedelta(seconds=LOCK_SECONDS)
                locked = True
                msg = f"Demasiados intentos. Espera {LOCK_SECONDS} s para volver a intentar."
            else:
                msg = f"Usuario o contraseña incorrectos. Intentos restantes: {MAX_TRIES - lock['tries']}."
    return render_template("admin_login.html", msg=msg, bad=bad, locked=locked,
                           usr=(request.form.get("usr") or "") if request.method == "POST" else "")


# ---------------------------------------------------------------- panel
@bp.get("/")
@admin_required
def panel():
    occ = L.occupancy()
    area = request.args.get("area") or request.args.get("area_cur")
    area = area if area in [a["id"] for a in AREAS] else "A"
    spot = request.args.get("spot") or request.args.get("sel") or None
    if spot and (spot[:1] != area or occ.get(spot) != "free"):
        spot = None
    q = L.norm(request.args.get("q"))

    t0 = L.today_start()
    ingresos = (db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).filter(Payment.at >= t0).scalar()
                + db.session.query(db.func.coalesce(db.func.sum(Reservation.fee_amount), 0))
                .filter(Reservation.fee_at >= t0).scalar())
    kpis = [
        ("Libres", sum(v == "free" for v in occ.values()), "free"),
        ("Reservados", sum(v == "resv" for v in occ.values()), "resv"),
        ("Ocupados", sum(v == "busy" for v in occ.values()), "busy"),
        ("Entradas hoy", Reservation.query.filter(Reservation.checkin >= t0).count(), ""),
        ("Ingresos hoy", f"${ingresos}", ""),
    ]

    rows = []
    for r in Reservation.query.filter(Reservation.status.in_(["reserved", "in"])).all():
        if not L.is_active(r):
            continue
        if q and not any(q in x for x in (L.norm(r.plate), L.norm(r.code), r.spot)):
            continue
        inn = r.status == "in"
        rows.append(dict(r=r, inn=inn, due=L.due_of(r) if inn else 0, emp=L.is_emp(r.plate),
                         dur=L.fmt_dur(L.now() - r.checkin) if inn else "—",
                         hora=L.hhmm(r.checkin if inn else r.start)))
    rows.sort(key=lambda x: x["r"].spot)

    return render_template(
        "admin.html", kpis=kpis, chart=Markup(L.chart_svg()), area=area, spot=spot,
        grid=L.area_grid(area, occ, spot), free=L.free_by_area(occ),
        plate=request.args.get("placa", ""), q=request.args.get("q", ""), rows=rows,
        emps=Employee.query.order_by(Employee.id).all(), fee=L.reservation_fee(L.now()),
    )


@bp.post("/empleados")
@admin_required
def emp_add():
    name = (request.form.get("nombre") or "").strip()[:40]
    plate = L.fmt_plate(request.form.get("placa"))
    if not name:
        flash("Escribe el nombre.", "bad")
    elif len(L.norm(plate)) < 5:
        flash("Escribe la placa completa (mínimo 5 caracteres).", "bad")
    elif L.is_emp(plate):
        flash("Esa placa ya está registrada.", "bad")
    else:
        db.session.add(Employee(name=name, plate=plate, plate_norm=L.norm(plate)))
        db.session.commit()
        flash("Empleado registrado.", "ok")
    return redirect(url_for("admin.panel") + "#empleados")


# ---------------------------------------------------------------- confirmar y ejecutar acciones
def _confirm_info(action, args):
    """Pantalla de confirmación (antes: el diálogo). Devuelve None si algo ya cambió."""
    code = args.get("code")
    r = db.session.get(Reservation, code) if code else None
    who = Markup('<b class="mono">%s</b>') % escape(r.plate) if r else ""
    sp = Markup("<b>%s</b>") % escape(r.spot) if r else ""
    if action == "checkin" and r:
        return dict(title="Confirmar check-in", ok="Sí, registrar entrada",
                    body=Markup("¿Registrar la entrada de %s en el cajón %s?") % (who, sp))
    if action == "cancel" and r:
        return dict(title="Cancelar reserva", ok="Sí, cancelar reserva", danger=True,
                    body=Markup("Vas a cancelar la reserva de %s en el cajón %s. El cajón quedará libre y "
                                "<b>esta acción no se puede deshacer</b>.") % (who, sp))
    if action == "out" and r and r.checkin:
        due = L.due_of(r)
        tail = (Markup("Por cobrar: <b>%s</b> en efectivo. El cajón quedará libre.") % L.money(due) if due > 0
                else Markup("Pago completo (%s). El cajón quedará libre.") % L.money(L.paid_of(r)))
        return dict(title="Cobrar y registrar salida" if due > 0 else "Registrar salida", danger=True,
                    ok="Sí, cobrar y salir" if due > 0 else "Sí, registrar salida",
                    body=Markup("Vehículo %s · cajón %s<br>Tiempo dentro: <b>%s</b><br>%s")
                    % (who, sp, L.fmt_dur(L.now() - r.checkin), tail))
    if action == "empdel":
        e = db.session.get(Employee, int(args.get("id") or 0))
        if e:
            return dict(title="Eliminar empleado", ok="Sí, eliminar", danger=True,
                        body=Markup('Vas a quitar a <b>%s</b> (<b class="mono">%s</b>) de la lista de empleados. '
                                    "<b>Esta acción no se puede deshacer</b>.") % (escape(e.name), escape(e.plate)))
    if action == "reservar":
        spot, plate = args.get("spot"), L.fmt_plate(args.get("placa"))
        if spot and len(L.norm(plate)) >= 5:
            fee = L.reservation_fee(L.now())
            return dict(title="Cobrar reservación", ok="Sí, cobrar y reservar",
                        body=Markup("Cajón <b>%s</b> para <b class=\"mono\">%s</b> (llega ahora).<br>"
                                    "Tarifa de reservación (%s): <b>%s</b> en efectivo. No es reembolsable.")
                        % (escape(spot), escape(plate), fee["label"], L.money(fee["amount"])))
    if action == "salir":
        return dict(title="Cerrar sesión", ok="Sí, cerrar sesión",
                    body="Saldrás del panel de administrador y tendrás que iniciar sesión de nuevo.")
    return None


_KEEP = ("code", "id", "spot", "placa")


@bp.get("/confirmar/<action>")
@admin_required
def confirm(action):
    args = request.args.to_dict()
    if not args.get("spot") and args.get("sel"):  # el cajón elegido viaja en "sel"
        args["spot"] = args["sel"]
    info = _confirm_info(action, args)
    if not info:
        flash("Esa reserva ya cambió. Se actualizó la lista.", "bad")
        return redirect(url_for("admin.panel"))
    return render_template("admin_confirm.html", action=action, info=info,
                           fields={k: args[k] for k in _KEEP if k in args},
                           back=url_for("admin.panel"))


@bp.post("/accion/<action>")
@admin_required
def do_action(action):
    f = request.form
    anchor = "#reservas"
    r = db.session.get(Reservation, f.get("code") or "")

    if action == "salir":
        session.pop("admin", None)
        return redirect(url_for("admin.login"))

    if action == "empdel":
        e = db.session.get(Employee, int(f.get("id") or 0))
        if e:
            db.session.delete(e)
            db.session.commit()
            flash("Empleado eliminado.", "ok")
        return redirect(url_for("admin.panel") + "#empleados")

    if action == "reservar":
        spot, plate = f.get("spot"), L.fmt_plate(f.get("placa"))
        if L.occupancy().get(spot) != "free":
            flash("Ese cajón ya no está libre.", "bad")
            return redirect(url_for("admin.panel") + "#cajones")
        fee = L.reservation_fee(L.now())
        rec = Reservation(code=L.new_code(), plate=plate, spot=spot, start=L.now(), status="reserved",
                          fee_amount=fee["amount"], fee_at=L.now(), fee_method="efectivo")
        db.session.add(rec)
        db.session.commit()
        flash(f"Cajón {spot} reservado para {plate} (código {rec.code}). Cobrado: {L.money(fee['amount'])}. "
              "Tiene 15 min para llegar.", "ok")
        return redirect(url_for("admin.panel") + "#cajones")

    # check-in / cancelar / salida: validar que la reserva no haya cambiado
    stale = (not r or not L.is_active(r) or (action == "checkin" and r.status != "reserved")
             or (action == "out" and r.status != "in"))
    if stale:
        flash("Esa reserva ya cambió. Se actualizó la lista.", "bad")
    elif action == "checkin":
        r.status, r.checkin = "in", L.now()
        db.session.commit()
        flash(f"Check-in registrado: {r.plate} en {r.spot}.", "ok")
    elif action == "cancel":
        r.status = "cancelled"
        db.session.commit()
        flash(f"Reserva de {r.plate} cancelada. El cajón {r.spot} quedó libre.", "ok")
    elif action == "out":
        due = L.due_of(r)
        if due > 0:
            L.add_payment(r, "efectivo", amount=due)
        L.do_exit(r)
        flash(f"Salida de {r.plate} ({r.spot}). "
              + (f"Cobrado en efectivo: {L.money(due)}." if due > 0 else f"Ya estaba pagado: {L.money(L.paid_of(r))}.")
              + (" Empleado: revisar si aplica descuento." if L.is_emp(r.plate) else ""), "ok")
    return redirect(url_for("admin.panel") + anchor)
