"""logic.py · Reglas de negocio de SmartPark (antes datos.js).
Estados de cajón, tarifas, cobros, validación, código de barras y gráfica."""
import math
import random
import re
from datetime import datetime, timedelta

from config import AREAS, HOLD, RATE, SPOTS_PER_AREA, TOL, TZ
from models import Employee, Payment, Plate, Reservation, db

HOUR = timedelta(hours=1)
DEAD = ("cancelled", "expired", "done")


# ---------------------------------------------------------------- tiempo y formato
def now():
    """Hora actual de la app (sin zona, redondeada al segundo)."""
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def hhmm(t):
    return t.strftime("%H:%M")


def fmt_dur(delta):
    s = max(0, int(delta.total_seconds()))
    h, m = s // 3600, (s % 3600) // 60
    return f"{h} h {m:02d} min" if h else f"{m:02d}:{s % 60:02d}"


def money(n):
    return f"${n} MXN"


DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def day_label(t):
    return f"{DIAS[t.weekday()]}, {t.day} {MESES[t.month - 1]}"


def clock_label(t):
    return t.strftime("%I:%M:%S ") + ("a.m." if t.hour < 12 else "p.m.")


# ---------------------------------------------------------------- placas
def norm(p):
    return re.sub(r"[^A-Za-z0-9]", "", str(p or "")).upper()


def fmt_plate(p):
    r = norm(p)
    return r[:3] + "-" + r[3:] if len(r) > 3 else r


def is_emp(plate):
    """Única definición: compara sin importar espacios o guiones."""
    return Employee.query.filter_by(plate_norm=norm(plate)).first() is not None


# ---------------------------------------------------------------- placas guardadas (base de la cámara)
def save_plate(plate_input, vehicle_type=None):
    """La cámara guarda aquí cada placa que lee. Devuelve (estado, Plate):
    invalid | new (primera vez) | known (ya estaba; solo se actualiza la última vez vista)."""
    raw = norm(plate_input)[:7]
    if len(raw) < 5:
        return "invalid", None
    n = now()
    p = Plate.query.filter_by(plate_norm=raw).first()
    if p:
        p.last_seen, p.hits = n, (p.hits or 0) + 1
        if vehicle_type and not p.vehicle_type:
            p.vehicle_type = vehicle_type
        db.session.commit()
        return "known", p
    p = Plate(plate=fmt_plate(raw), plate_norm=raw, vehicle_type=vehicle_type, first_seen=n, last_seen=n)
    db.session.add(p)
    db.session.commit()
    return "new", p


def plate_known(plate_input):
    """¿Esta placa está en la base? Sí si la cámara la guardó, si es de un empleado
    o si ya tiene una reserva vigente (la pagó al reservar)."""
    raw = norm(plate_input)[:7]
    if Plate.query.filter_by(plate_norm=raw).first() or is_emp(raw):
        return True
    cand = Reservation.query.filter(Reservation.status.in_(["in", "reserved"])).all()
    return any(is_active(x) and norm(x.plate) == raw for x in cand)


# ---------------------------------------------------------------- cajones
def spot_ids(area_id):
    return [f"{area_id}{i:02d}" for i in range(1, SPOTS_PER_AREA + 1)]


def area_by_id(area_id):
    return next((a for a in AREAS if a["id"] == area_id), None)


def is_active(r, t=None):
    t = t or now()
    if r.status == "hold":
        return r.hold_until is not None and t < r.hold_until
    if r.status in DEAD:
        return False
    if r.status == "reserved" and t > r.start + TOL:
        return False
    return True


def occupancy():
    """{cajón: 'free' | 'resv' | 'busy'} con UNA sola consulta."""
    t = now()
    occ = {s: "free" for a in AREAS for s in spot_ids(a["id"])}
    rows = Reservation.query.filter(Reservation.status.in_(["hold", "reserved", "in"])).all()
    for r in rows:
        if not is_active(r, t) or r.spot not in occ:
            continue
        if r.status == "in":
            occ[r.spot] = "busy"
        elif occ[r.spot] != "busy":
            occ[r.spot] = "resv"
    return occ


def first_free(occ=None):
    occ = occ or occupancy()
    for a in AREAS:
        for s in spot_ids(a["id"]):
            if occ[s] == "free":
                return s
    return None


def count_free(occ=None):
    occ = occ or occupancy()
    return sum(1 for v in occ.values() if v == "free")


def area_grid(area_id, occ, selected=None, interactive=True):
    """Datos para dibujar el mapa de un área (4 cajones arriba, 4 abajo)."""
    out = []
    for s in spot_ids(area_id):
        st = occ.get(s, "free")
        on = s == selected
        out.append(
            {
                "id": s,
                "state": "sel" if on else st,
                "label": "Tu cajón" if on else {"free": "Libre", "resv": "Reservado", "busy": "Ocupado"}[st],
                "can": interactive and (st == "free" or on),
            }
        )
    return out


def free_by_area(occ):
    return {a["id"]: sum(1 for s in spot_ids(a["id"]) if occ[s] == "free") for a in AREAS}


def new_code():
    while True:
        c = f"SP-{random.randint(1000, 9999)}"
        if not db.session.get(Reservation, c):
            return c


# ---------------------------------------------------------------- registro de entrada
def register_entry(plate_input, source="web", vehicle_type=None, only_known=False):
    """Registra la entrada de una placa. La usan la página web (/acceso) y la cámara,
    así las dos aplican EXACTAMENTE las mismas reglas.

    Devuelve {"status", "r", "msg"} con status:
      invalid | inside (ya estaba dentro) | early (reserva muy temprano)
      checkin (reserva confirmada) | walkin (entrada nueva) | full (sin lugar)
      unknown (solo con only_known=True: la placa no está en la base)"""
    raw = norm(plate_input)[:7]
    if len(raw) < 5:
        return {"status": "invalid", "r": None, "msg": "Escribe la placa completa (mínimo 5 caracteres)."}

    if only_known and not plate_known(raw):
        return {"status": "unknown", "r": None,
                "msg": "Placa no registrada. Solo pueden entrar las placas que la cámara ya detectó."}

    cand = Reservation.query.filter(Reservation.status.in_(["in", "reserved"])).all()
    r = next((x for x in cand if is_active(x) and norm(x.plate) == raw), None)

    if r and r.status == "in":
        return {"status": "inside", "r": r, "msg": f"Ya está dentro: cajón {r.spot}."}

    if r and r.status == "reserved":
        if now() < r.start - TOL:
            return {"status": "early", "r": r,
                    "msg": f"Tu reserva empieza a las {hhmm(r.start)}. El acceso abre 15 min antes."}
        r.status, r.checkin = "in", now()
        if vehicle_type and not r.vehicle_type:
            r.vehicle_type = vehicle_type
        db.session.commit()
        return {"status": "checkin", "r": r, "msg": f"Reserva confirmada: cajón {r.spot}."}

    spot = first_free()
    if not spot:
        return {"status": "full", "r": None, "msg": "El estacionamiento está lleno por ahora."}
    n = now()
    w = Reservation(code=new_code(), plate=fmt_plate(raw), spot=spot, start=n, checkin=n, status="in",
                    walkin=True, vehicle_type=vehicle_type, source=source)
    db.session.add(w)
    db.session.commit()
    return {"status": "walkin", "r": w, "msg": f"Entrada registrada: cajón {spot}."}


# ---------------------------------------------------------------- tarifa de reservación
def reservation_fee(dt):
    """Se paga al reservar y depende del día y la hora de LLEGADA.
    Es independiente de la tarifa por hora de estacionamiento.
    Para cambiar los precios, edita los números de esta función."""
    dow = dt.weekday()  # 0 = lunes ... 6 = domingo
    h = dt.hour + dt.minute / 60
    if h >= 22 or h < 6:
        return {"amount": 15, "label": "Horario nocturno"}
    if dow in (4, 5) and h >= 18:
        return {"amount": 40, "label": "Noche de viernes o sábado"}
    if dow in (5, 6) and 10 <= h < 18:
        return {"amount": 35, "label": "Fin de semana"}
    if dow <= 4 and (7 <= h < 10 or 17 <= h < 20):
        return {"amount": 30, "label": "Hora pico"}
    return {"amount": 20, "label": "Tarifa base"}


# ---------------------------------------------------------------- cobro
# Se cobra por hora iniciada. Tras pagar hay 15 min (TOL) para salir sin cargo extra;
# pasado ese tiempo se cobra la diferencia.
def cost_of(r, t=None):
    end = t or r.exit_at or now()
    hours = max(1, math.ceil((end - r.checkin) / HOUR))
    return hours * RATE


def paid_of(r):
    return sum(p.amount for p in r.payments)


def due_of(r):
    if not r.checkin or r.status == "done":
        return 0
    if r.payments:
        last = r.payments[-1].at
        if now() <= last + TOL:
            return max(0, cost_of(r, last) - paid_of(r))
    return max(0, cost_of(r) - paid_of(r))


def grace_until(r):
    if not r.payments or due_of(r) > 0:
        return None
    return r.payments[-1].at + TOL


def add_payment(r, method, ref=None, amount=None):
    """Registra un pago. Guarda SOLO método, monto y folio; nunca datos de tarjeta."""
    amount = due_of(r) if amount is None else amount
    if amount <= 0:
        return None
    p = Payment(reservation_code=r.code, at=now(), amount=amount, method=method, ref=ref)
    db.session.add(p)
    db.session.commit()
    db.session.refresh(r)
    return p


def do_exit(r):
    """Registra la salida y BORRA la placa de la tabla `placas`: para volver a entrar
    la cámara tiene que guardarla otra vez. El historial (visita y pagos) se conserva."""
    r.status = "done"
    r.exit_at = now()
    Plate.query.filter_by(plate_norm=norm(r.plate)).delete()
    db.session.commit()


def inside_by_plate(plate_input):
    """Visita en curso (status 'in') de una placa, o None."""
    raw = norm(plate_input)[:7]
    if len(raw) < 5:
        return None
    return next((x for x in Reservation.query.filter_by(status="in").all() if norm(x.plate) == raw), None)


def mark_expired(r):
    """Si una reserva ya venció la marca como 'expired' en la base."""
    if r.status == "reserved" and now() > r.start + TOL:
        r.status = "expired"
        db.session.commit()


# ---------------------------------------------------------------- estado del boleto de reserva
def ticket_status(r):
    """Texto y clase de la franja de estado del boleto de reservación."""
    n = now()
    if r.status == "in":
        return "in", f"Dentro desde las {hhmm(r.checkin)} · {fmt_dur(n - r.checkin)} estacionado"
    if r.status == "done":
        return "in", "Salida registrada. ¡Gracias por tu visita!"
    if r.status in ("expired", "cancelled"):
        return "dead", "Reserva vencida: tu cajón se liberó"
    if n < r.start:
        return "", f"Tu reserva empieza en {fmt_dur(r.start - n)}"
    left = r.start + TOL - n
    cls = "warn" if left < timedelta(minutes=10) else ""
    return cls, f"Llega en {fmt_dur(left)} o se libera tu cajón"


# ---------------------------------------------------------------- tarjetas (solo validación)
def luhn(n):
    if not re.fullmatch(r"\d{13,19}", n):
        return False
    s, alt = 0, False
    for ch in reversed(n):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        alt = not alt
    return s % 10 == 0


def card_error(number, exp, cvv):
    """Valida los campos de la tarjeta. Devuelve el mensaje de error o ''. No guarda nada."""
    n = re.sub(r"\D", "", number or "")
    if not luhn(n):
        return "Revisa el número de tarjeta."
    d = re.sub(r"\D", "", exp or "")
    if len(d) != 4 or not 1 <= int(d[:2]) <= 12:
        return "Fecha de vencimiento inválida (MM/AA)."
    t = now()
    y, mo = 2000 + int(d[2:]), int(d[:2])
    if y < t.year or (y == t.year and mo < t.month):
        return "La tarjeta está vencida."
    if not re.fullmatch(r"\d{3,4}", cvv or ""):
        return "El CVV debe tener 3 o 4 dígitos."
    return ""


# ---------------------------------------------------------------- código de barras (Code 39)
_C39 = {
    "0": "nnnwwnwnn", "1": "wnnwnnnnw", "2": "nnwwnnnnw", "3": "wnwwnnnnn", "4": "nnnwwnnnw",
    "5": "wnnwwnnnn", "6": "nnwwwnnnn", "7": "nnnwnnwnw", "8": "wnnwnnwnn", "9": "nnwwnnwnn",
    "A": "wnnnnwnnw", "B": "nnwnnwnnw", "C": "wnwnnwnnn", "D": "nnnnwwnnw", "E": "wnnnwwnnn",
    "F": "nnwnwwnnn", "G": "nnnnnwwnw", "H": "wnnnnwwnn", "I": "nnwnnwwnn", "J": "nnnnwwwnn",
    "K": "wnnnnnnww", "L": "nnwnnnnww", "M": "wnwnnnnwn", "N": "nnnnwnnww", "O": "wnnnwnnwn",
    "P": "nnwnwnnwn", "Q": "nnnnnnwww", "R": "wnnnnnwwn", "S": "nnwnnnwwn", "T": "nnnnwnwwn",
    "U": "wwnnnnnnw", "V": "nwwnnnnnw", "W": "wwwnnnnnn", "X": "nwnnwnnnw", "Y": "wwnnwnnnn",
    "Z": "nwwnwnnnn", "-": "nwnnnnwnw", ".": "wwnnnnwnn", " ": "nwwnnnwnn", "*": "nwnnwnwnn",
}


def code39(text):
    """Lista de (ancho en módulos, es_barra)."""
    out = []
    for ch in "*" + str(text).upper() + "*":
        pat = _C39.get(ch)
        if not pat:
            continue
        for i, c in enumerate(pat):
            out.append((3 if c == "w" else 1, i % 2 == 0))
        out.append((1, False))
    return out


def barcode_svg(text, h=60):
    units = code39(text)
    total = sum(w for w, _ in units)
    x, rects = 0, []
    for w, bar in units:
        if bar:
            rects.append(f'<rect x="{x}" y="0" width="{w}" height="{h}"/>')
        x += w
    return (
        f'<svg viewBox="0 0 {total} {h}" preserveAspectRatio="none" width="100%" height="100%" '
        f'role="img" aria-label="Código de barras {text}" fill="#111">{"".join(rects)}</svg>'
    )


# ---------------------------------------------------------------- gráfica de entradas (SVG)
def today_start():
    n = now()
    return datetime(n.year, n.month, n.day)


def entries_by_day(days=7):
    """Entradas reales por día: cuenta los vehículos que entraron (checkin) en cada uno de los
    últimos `days` días, terminando hoy. Devuelve [(fecha, cantidad), ...] del más viejo a hoy."""
    t0 = today_start()
    first = t0 - timedelta(days=days - 1)
    counts = {first + timedelta(days=i): 0 for i in range(days)}
    for (ck,) in db.session.query(Reservation.checkin).filter(Reservation.checkin >= first).all():
        d = datetime(ck.year, ck.month, ck.day)
        if d in counts:
            counts[d] += 1
    return sorted(counts.items())


def chart_svg():
    data = entries_by_day(7)
    h = [c for _, c in data]
    idx = len(h) - 1  # hoy es la última barra
    DIAS = ["L", "M", "M", "J", "V", "S", "D"]
    dias = [DIAS[d.weekday()] for d, _ in data]
    top = math.ceil((max(h) + 1) / 10) * 10
    x0, y0, ph, pw, bw = 46, 170, 140, 340, 30
    st = pw / 7
    dias = ["L", "M", "M", "J", "V", "S", "D"]
    s = []
    for k in range(5):
        y = y0 - ph * k / 4
        s.append(
            f'<line class="gl" x1="{x0}" x2="{x0 + pw}" y1="{y}" y2="{y}"/>'
            f'<text class="ax" x="{x0 - 6}" y="{y + 4}" text-anchor="end">{round(top * k / 4)}</text>'
        )
    for i, v in enumerate(h):
        bh = ph * v / top
        x = x0 + st * i + (st - bw) / 2
        s.append(
            f'<rect class="bar{" today" if i == idx else ""}" x="{x:.1f}" y="{y0 - bh:.1f}" width="{bw}" '
            f'height="{bh:.1f}" rx="3"><title>{data[i][0]:%d/%m}: {v} entradas</title></rect>'
            f'<text class="bv" x="{x + bw / 2:.1f}" y="{y0 - bh - 4:.1f}">{v}</text>'
            f'<text class="ax" style="font-size:13px;font-weight:{700 if i == idx else 400}" '
            f'x="{x + bw / 2:.1f}" y="190" text-anchor="middle">{dias[i]}</text>'
        )
    s.append('<text class="ax" transform="rotate(-90 11 100)" x="11" y="100" text-anchor="middle">Vehículos</text>')
    return "".join(s)


# ---------------------------------------------------------------- datos de ejemplo
def seed_demo():
    """Carga los vehículos DEMO la primera vez (la base está vacía)."""
    if Reservation.query.count():
        return
    n, m = now(), timedelta(minutes=1)
    rows = [
        ("SP-0001", "DEMO1", "A03", n - 60 * m, n - 60 * m, "in"),
        ("SP-0002", "DEMO2", "B02", n - 30 * m, n - 25 * m, "in"),
        ("SP-0003", "DEMO3", "A05", n + 30 * m, None, "reserved"),
        ("SP-0004", "DEMO4", "B04", n + 60 * m, None, "reserved"),
        ("SP-0005", "DEMO5", "C01", n - 2 * m, n - 1 * m, "in"),
        ("SP-0006", "DEMO6", "D06", n + 10 * m, None, "reserved"),
        ("SP-0007", "DEMO7", "E02", n - 120 * m, n - 120 * m, "in"),
        ("SP-0008", "DEMO8", "F08", n + 20 * m, None, "reserved"),
    ]
    for code, plate, spot, start, checkin, status in rows:
        db.session.add(Reservation(code=code, plate=plate, spot=spot, start=start, checkin=checkin, status=status))
    db.session.commit()
