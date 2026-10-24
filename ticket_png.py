"""ticket_png.py · Genera el boleto o el recibo como imagen PNG (antes: canvas en boleto.js)."""
import io
import os

from PIL import Image, ImageDraw, ImageFont

from logic import code39, cost_of, due_of, fmt_dur, fmt_plate, money, now, paid_of

_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial.ttf",
]
_BOLD = [p.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf").replace("segoeui", "segoeuib").replace("arial", "arialbd") for p in _FONTS]
_MONO = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
    "C:/Windows/Fonts/consolab.ttf",
    "C:/Windows/Fonts/cour.ttf",
]


def _font(paths, size):
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)  # Pillow >= 10.1


def build(r):
    paid, due = paid_of(r), due_of(r)
    settled = paid > 0 and due == 0
    end = r.exit_at or now()
    W, H = 720, 1120
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([7, 7, W - 8, H - 8], outline="#f5c400", width=14)

    d.text((W / 2, 110), "SMARTPARK", font=_font(_BOLD, 54), fill="#111", anchor="ms")
    sub = "Recibo de pago" if settled or r.status == "done" else "Boleto digital de entrada"
    d.text((W / 2, 155), sub, font=_font(_FONTS, 26), fill="#6b7790", anchor="ms")

    def line(label, value, y, color="#1c2333", size=40):
        d.text((70, y), label, font=_font(_BOLD, 22), fill="#6b7790", anchor="ls")
        d.text((70, y + 46), value, font=_font(_MONO, size), fill=color, anchor="ls")

    line("BOLETO #", r.code, 225)
    line("PLACA REGISTRADA", fmt_plate(r.plate), 335)
    line("CAJÓN ASIGNADO", f"{r.spot[0]}-{r.spot[1:]}  (Área {r.spot[0]})", 445, "#b86a00", 44)
    line("HORA DE ENTRADA", r.checkin.strftime("%d/%m/%Y %H:%M"), 555)
    line("TIEMPO DENTRO", fmt_dur(end - r.checkin), 665)
    if settled:
        line("TOTAL PAGADO", money(paid), 775, "#15704a", 44)
    else:
        line("TOTAL A PAGAR", money(due), 775, "#1c2333", 44)

    # Código de barras
    units = code39(r.code)
    total = sum(w for w, _ in units)
    mod = (W - 140) // total
    x = (W - mod * total) // 2
    for w, bar in units:
        if bar:
            d.rectangle([x, 880, x + w * mod - 1, 1010], fill="#111")
        x += w * mod
    d.text((W / 2, 1050), r.code, font=_font(_MONO, 26), fill="#6b7790", anchor="ms")

    buf = io.BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    return buf, ("recibo-" if settled else "ticket-") + r.code + ".png"
