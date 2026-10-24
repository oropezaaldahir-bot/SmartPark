"""pasarela.py · Pasarela de pago SIMULADA.

Es una pantalla aparte que imita una pasarela real (Mercado Pago, Stripe, Conekta…).
- Los datos de la tarjeta solo se validan en esta vista y se descartan: no se guardan en la
  base de datos, ni en la sesión, ni en archivos de registro.
- SmartPark recibe únicamente el resultado (aprobado / cancelado / vencido) y un folio.

Con una pasarela real, el cliente teclea la tarjeta en el sitio de la pasarela (los datos jamás
pasan por tu servidor) y ella te avisa el resultado; aquí esta vista hace ese papel."""
import random
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from config import DEMO_PAGOS
from logic import add_payment, card_error, money, now
from models import Reservation, db

bp = Blueprint("pasarela", __name__, url_prefix="/pasarela")

CHECKOUT_MIN = 10  # minutos de vigencia de la sesión de pago


def start_checkout(kind, amount, label, return_url, code):
    """Guarda en la sesión qué se va a pagar y a dónde regresar. Nunca datos de tarjeta."""
    session["checkout"] = {
        "id": "CK-%06d" % random.randint(0, 999999),
        "kind": kind,  # "ticket" | "reservation"
        "amount": amount,
        "label": label,
        "return": return_url,
        "code": code,
        "expires": (now() + timedelta(minutes=CHECKOUT_MIN)).isoformat(),
    }
    return redirect(url_for("pasarela.ver"))


def _intent():
    c = session.get("checkout")
    if not c:
        return None
    try:
        c = dict(c, expires=datetime.fromisoformat(c["expires"]))
    except (KeyError, ValueError):
        return None
    return c


def complete_checkout(c, status, folio=None):
    """Aplica el resultado del pago. Se ejecuta una sola vez (después se borra la sesión de pago)."""
    session.pop("checkout", None)
    r = db.session.get(Reservation, c["code"])
    if c["kind"] == "ticket":
        if status == "ok" and r:
            add_payment(r, "tarjeta", ref=folio, amount=c["amount"])
            flash(f"Pago de {money(c['amount'])} aprobado. Folio {folio}.", "ok")
            return
    elif c["kind"] == "reservation":
        if status == "ok" and r and r.status == "hold":
            r.status = "reserved"
            r.hold_until = None
            r.fee_amount, r.fee_at, r.fee_method, r.fee_ref = c["amount"], now(), "tarjeta", folio
            db.session.commit()
            session["mine"] = r.code
            flash(f"Reservación pagada: {money(c['amount'])}. Folio {folio}.", "ok")
            return
        if r and r.status == "hold":  # cancelado o vencido: se libera el cajón
            db.session.delete(r)
            db.session.commit()
    flash(
        "La sesión de pago venció. No se hizo ningún cargo."
        if status == "expired"
        else "Pago cancelado. No se hizo ningún cargo.",
        "bad",
    )


@bp.route("/", methods=["GET", "POST"])
def ver():
    c = _intent()
    if not c:
        return render_template("pasarela.html", state="none")
    if now() > c["expires"]:
        complete_checkout(c, "expired")
        return redirect(c["return"])

    msg = ""
    if request.method == "POST":
        if "cancelar" in request.form:
            complete_checkout(c, "cancelled")
            return redirect(c["return"])
        # La tarjeta solo se valida; no se guarda ni se vuelve a mostrar.
        msg = card_error(request.form.get("cc"), request.form.get("exp"), request.form.get("cvv"))
        if not msg:
            folio = "PG-%06d" % random.randint(0, 999999)
            complete_checkout(c, "ok", folio)
            return render_template("pasarela.html", state="done", folio=folio, ret=c["return"])

    return render_template(
        "pasarela.html", state="pay", c=c, amount=money(c["amount"]), msg=msg, demo=DEMO_PAGOS
    )
