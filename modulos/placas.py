"""Clasificación de placas por formato de texto.
 
Fuente ÚNICA: NOM-001-SCT-2-2016 (DOF), Apéndice B Normativo, Tabla C
"Conformación de los caracteres de identificación (letras y dígitos)".
 
Notación de la norma:  A = letra   0 = dígito   (los guiones son solo separación visual).
Según la norma, en los caracteres alfabéticos NO se usan las letras I, Ñ, O, Q.
 
Una misma conformación puede servir a varios tipos de vehículo (p. ej. 00-AA-0A
es de automóviles, camiones y grúas federales), por eso el resultado puede traer
más de un tipo posible. Si ningún formato coincide => "Desconocido".
Formatos de autobuses, remolques, tractocamiones y convertidores no se incluyen
(fuera de las 4 categorías pedidas) y por tanto darán "Desconocido".
"""
import re
 
AUTO, CAMION, MOTO, GRUA = "Automóvil", "Camión", "Motocicleta", "Grúa"
OTRO = "Otro"  # servicios especiales cuyo tipo de vehículo la norma no precisa
DESCONOCIDO = "Desconocido"
 
# Letras válidas: A-Z sin I, Ñ, O, Q
LETRA = "ABCDEFGHJKLMNPRSTUVWXYZ"
 
# (formato compacto, tipos, servicio / figura de la norma)
_FORMATOS = [
    # ---------------- Autotransporte federal ----------------
    ("00AA0A", (AUTO,),          "Federal: arrendamiento de uso particular (Automóviles)"),
    ("00AA0A", (CAMION,),        "Federal: carga/transfronterizo/internacional (Unidades motrices)"),
    ("00AA0A", (GRUA,),          "Federal: grúas de arrastre, arrastre y salvamento e industriales"),
    ("00A0AA", (AUTO, CAMION, GRUA), "Federal: traslado nacional (todo tipo de vehículos)"),
    ("AA000A", (MOTO,),          "Federal: traslado nacional (motocicletas)"),
    ("000A",   (OTRO,),          "Federal: capacidades diferentes"),
    ("AA00",   (OTRO,),          "Federal: inspección de vías generales de comunicación SCT"),
    # ---------------- Fronterizo ----------------
    ("A00AAA0", (AUTO,),         "Transporte privado fronterizo: automóviles"),
    ("AAA000A", (CAMION, GRUA),  "Transporte privado fronterizo: camiones y grúas"),
    ("A000AAA", (AUTO, CAMION, GRUA), "Público local fronterizo / público local entidades (autos, camiones, grúas)"),
    # ---------------- Corporaciones policiacas ----------------
    ("AA000A0", (AUTO, CAMION, GRUA), "Corporaciones policiacas y de vigilancia: patrullas"),
    ("AA00A",   (MOTO,),         "Corporaciones policiacas: patrullas tipo motocicleta / motocicletas entidades"),
    ("AA0000A", (AUTO, CAMION, GRUA), "Policía Federal (patrullas) / privado entidades camiones y grúas"),
    # ---------------- Demostración ----------------
    ("DMAA0",   (AUTO, CAMION, GRUA), "Demostración Ciudad de México (todo tipo de vehículos)"),
    ("0AA00A",  (AUTO, CAMION, GRUA), "Demostración entidades federativas (todo tipo de vehículos)"),
    ("A000A",   (MOTO,),         "Demostración motocicleta"),
    # ---------------- Transporte privado ----------------
    ("A00AAA",  (AUTO,),         "Privado Ciudad de México: automóviles"),
    ("A000AA",  (CAMION, GRUA),  "Privado Ciudad de México: camiones y grúas"),
    ("AAA000A", (AUTO,),         "Privado entidades federativas: automóviles"),
    ("A00AA",   (MOTO,),         "Privado motocicleta"),
    ("0A0AA",   (MOTO,),         "Privado motocicleta"),
    ("A0AA0",   (MOTO,),         "Privado motocicleta"),
    ("0AA00",   (AUTO,),         "Auto antiguo Ciudad de México"),
    ("AA0A",    (AUTO,),         "Auto antiguo entidades federativas"),
    # ---------------- Público local ----------------
    ("A0000A",  (AUTO,),         "Público local CDMX libre o sitio"),
    ("000A000", (OTRO,),         "Público local CDMX con itinerario fijo"),
    ("000000",  (CAMION, GRUA),  "Público local CDMX: autobuses, camiones, grúas y remolques"),
    ("0AAA00A", (CAMION, GRUA),  "Público local entidades: camiones y grúas"),
    ("AA0AA",   (MOTO,),         "Público local motocicleta (CDMX y entidades)"),
    ("0AAA0",   (MOTO,),         "Público local motocicleta (entidades)"),
    # ---------------- Servicios especiales ----------------
    ("00A000",  (OTRO,),         "Vehículo ecológico"),
    ("AA000AA", (OTRO,),         "Ambulancias / Bomberos"),
    ("00AA000", (AUTO, CAMION, GRUA, MOTO), "Protección civil (todos los vehículos)"),
    ("AAA00AA", (AUTO,),         "Escoltas Ciudad de México: automóviles"),
    ("AAA0AA",  (MOTO,),         "Escoltas Ciudad de México: motocicletas"),
    ("00A00",   (AUTO, CAMION, GRUA, MOTO), "Capacidades diferentes CDMX (todos los vehículos)"),
    ("00AAA",   (AUTO, CAMION, GRUA, MOTO), "Capacidades diferentes entidades (todos los vehículos)"),
]
# Paquetería y mensajería (00A-0AA): la norma no precisa el tipo de vehículo
_FORMATOS.append(("00A0AA", (OTRO,), "Federal: paquetería y mensajería"))
# Vehículos de diagnóstico (AA-A000): tipo no especificado
_FORMATOS.append(("AAA000", (OTRO,), "Federal: vehículos de diagnóstico (fabricantes)"))
 
 
def _regex(fmt: str) -> "re.Pattern":
    partes = []
    for c in fmt:
        partes.append(f"[{LETRA}]" if c == "A" else r"\d" if c == "0" else re.escape(c))
    return re.compile("^" + "".join(partes) + "$")
 
 
_ORDEN = [AUTO, CAMION, MOTO, GRUA, OTRO]
_REGEX = [(_regex(f), t, s, f) for f, t, s in _FORMATOS]
 
# Confusiones típicas de OCR (solo se usan si el texto exacto no coincide)
_LETRA_A_DIGITO = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8"}
_DIGITO_A_LETRA = {"0": "D", "5": "S", "2": "Z", "6": "G", "8": "B", "1": "L"}
 
 
def _normalizar(token: str) -> str:
    return re.sub(r"[^A-Z0-9Ñ]", "", token.upper())
 
 
def _corregir(cand: str, fmt: str) -> str:
    out = []
    for ch, p in zip(cand, fmt):
        if p == "0" and ch in _LETRA_A_DIGITO:
            ch = _LETRA_A_DIGITO[ch]
        elif p == "A" and ch in _DIGITO_A_LETRA:
            ch = _DIGITO_A_LETRA[ch]
        out.append(ch)
    return "".join(out)
 
 
def _cambios(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b))
 
 
def _coincidencias(cand: str, corregir: bool):
    res = []
    for rx, tipos, servicio, fmt in _REGEX:
        if len(cand) != len(fmt):
            continue
        if rx.match(cand):
            res.append((tipos, servicio, fmt, False))
        elif corregir and len(fmt) >= 5 and rx.match(_corregir(cand, fmt)) and _cambios(cand, _corregir(cand, fmt)) <= 1:
            res.append((tipos, servicio, fmt, True))
    return res
 
 
def clasificar_formato(texto: str, corregir_ocr: bool = True, max_tokens: int = 4) -> dict:
    """Busca una placa dentro del texto del OCR y devuelve su clasificación.
 
    Devuelve: {"tipo": str, "tipos": [..], "placa": str|None, "servicios": [..],
               "formatos": [..], "corregida": bool}
    tipo = "Automóvil", "Camión", "Motocicleta", "Grúa", varios unidos por " / "
           si el formato es compartido, o "Desconocido".
    """
    tokens = [t for t in (_normalizar(x) for x in re.split(r"\s+", texto or "")) if t]
    # Ventanas contiguas de tokens (la placa puede salir partida: "ABC 123 D"); más largas primero
    candidatos = []
    for n in range(min(max_tokens, len(tokens)), 0, -1):
        for i in range(len(tokens) - n + 1):
            c = "".join(tokens[i:i + n])
            if any(ch.isdigit() for ch in c) or corregir_ocr:
                candidatos.append(c)
    for corregir in (False, True) if corregir_ocr else (False,):
        for c in candidatos:
            if not 4 <= len(c) <= 7:
                continue
            if sum(ch.isdigit() for ch in c) == 0 and not c.startswith("DM"):
                continue
            m = _coincidencias(c, corregir)
            if m:
                tipos = []
                for t, _, _, _ in m:
                    for x in t:
                        if x not in tipos:
                            tipos.append(x)
                tipos.sort(key=lambda x: _ORDEN.index(x))
                placa = c if not corregir else _corregir(c, m[0][2])
                return {
                    "tipo": " / ".join(tipos), "tipos": tipos, "placa": placa,
                    "servicios": [s for _, s, _, _ in m],
                    "formatos": sorted({f for _, _, f, _ in m}),
                    "corregida": corregir,
                }
    return {"tipo": DESCONOCIDO, "tipos": [], "placa": None,
            "servicios": [], "formatos": [], "corregida": False}
 
 
# ---- Interfaz compatible con el módulo anterior ----
def limpiar_placa(placa: str) -> str:
    """Normaliza el texto: mayúsculas y solo letras/números."""
    return re.sub(r"[^A-Z0-9]", "", placa.strip().upper())
 
 
def clasificar_placa(placa: str) -> str:
    """Devuelve el tipo ('Automóvil', 'Camión / Grúa', ..., 'Desconocido')."""
    return clasificar_formato(placa)["tipo"]
 
 
def extraer_placa(texto: str, max_correcciones: int = 1):
    """Busca la placa en el texto del OCR. Devuelve (placa, tipo) o (None, 'Desconocido')."""
    r = clasificar_formato(texto, corregir_ocr=max_correcciones > 0)
    return r["placa"], r["tipo"]
 
 
if __name__ == "__main__":
    pruebas = ["ABC-123-D", "A12-BCD", "AB-1234-C", "12-AB-3C", "AB123C", "A123B", "000-000",
               "1D-12-AB", "XYZ", "HOLA MUNDO", "CIUDAD DE MEXICO AB 12 3 C", "OB-1234-C", "AA-1O-3C"]
    for p in pruebas:
        r = clasificar_formato(p)
        print(f"{p!r:35} -> {r['tipo']:35} {r['placa']} {'(corregida)' if r['corregida'] else ''}")
 
 
def tipo_para_bd(tipo: str) -> str:
    """Texto corto (<= 12 caracteres, límite de la columna vehicle_type) para guardar en la BD.
    Un solo tipo se guarda tal cual; si el formato es compartido por varios tipos -> 'Varios'."""
    return tipo if " / " not in tipo else "Varios"