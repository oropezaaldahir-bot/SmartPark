"""Módulo principal: DOS cámaras simultáneas (entrada y salida) en un solo programa.

    python main.py             # las dos cámaras a la vez (cada una en su ventana)
    python main.py entrada     # solo la de entrada
    python main.py salida      # solo la de salida

Teclas:  ESPACIO -> OCR en las cámaras abiertas (lee la placa; en la de salida también busca la tarifa)
         E       -> cámara de ENTRADA: guarda la placa en la base de datos
         S       -> cámara de SALIDA: deja salir SOLO si ya pagó; registra la salida y borra la placa
         q / ESC -> salir
(Se confirma con E / S para no usar una lectura equivocada del OCR.)
"""
import os
import sys

import cv2

from modulos import camara, ocr, interfaz, zona_placa, detector_placa, registro
from modulos.placas import extraer_placa

# Índice USB de cada cámara (0, 1, 2...). Cámbialos sin tocar el código:
#   (Windows)  set CAMARA_ENTRADA=0 && set CAMARA_SALIDA=1 && python main.py
#   (PowerShell)  $env:CAMARA_ENTRADA="0"; $env:CAMARA_SALIDA="1"
INDICES = {
    "entrada": int(os.getenv("CAMARA_ENTRADA", "0")),
    "salida": int(os.getenv("CAMARA_SALIDA", "1")),
}
AYUDA = {
    "entrada": "ESPACIO=detectar  E=guardar placa  Q=salir",
    "salida": "ESPACIO=detectar y cobrar  S=dejar salir  Q=salir",
}
TITULO = {"entrada": "Camara de ENTRADA", "salida": "Camara de SALIDA"}


def procesar_ocr(frame, zona, nombre):
    """OCR sobre la zona de la placa. Devuelve (texto a mostrar, (placa, tipo) o None)."""
    recorte = zona_placa.recortar_zona(frame, zona)
    if recorte is None:
        print(f"[{nombre}] No se encontró zona de placa")
        return "Sin zona de placa", None

    ocr.detectar_texto(recorte)  # OCR solo dentro de la zona
    texto = ocr.obtener_texto()
    print(f"[{nombre}] Texto detectado:", texto)

    placa, tipo = extraer_placa(texto)  # elige del texto la parte que realmente es una placa
    if placa:
        print(f"[{nombre}] Placa: {placa} | Tipo: {tipo}")
        return f"{placa} - {tipo}", (placa, tipo)
    print(f"[{nombre}] No se reconoció una placa válida")
    return "Placa no reconocida", None


def main(modos=("entrada", "salida")):
    ocr.iniciar_ocr()
    detector_placa.cargar_modelo()

    # Abre cada cámara en su propio hilo (siempre guarda el frame más reciente)
    cams = {}
    try:
        for modo in modos:
            try:
                cams[modo] = camara.CamaraHilo(INDICES[modo])
            except RuntimeError:
                print(f"[{modo.upper()}] No se pudo abrir la cámara con índice {INDICES[modo]}. "
                      f"Revisa el puerto USB o cambia CAMARA_{modo.upper()}.")
        if not cams:
            return
    except BaseException:
        for c in cams.values():
            c.cerrar()
        raise

    # Estado de cada cámara: lo que muestra, el resultado en la base y la placa esperando confirmación
    mensajes = {m: "" for m in cams}
    estados = {m: "" for m in cams}
    pendientes = {m: None for m in cams}
    print("ESPACIO -> OCR | E -> guardar placa (entrada) | S -> dejar salir (salida) | q / ESC -> salir")

    try:
        while True:
            frames, zonas = {}, {}
            for modo, cam in cams.items():
                ret, frame = cam.leer()
                frames[modo] = frame if ret else None
                if not ret:
                    zonas[modo] = None
                    continue
                zonas[modo] = detector_placa.detectar_zona_placa(frame)  # YOLO en cada frame
                interfaz.dibujar_frame(frame, mensajes[modo], zonas[modo], titulo=TITULO[modo],
                                       estado=estados[modo], ayuda=AYUDA[modo])

            tecla = interfaz.leer_tecla()  # una sola vez por vuelta

            if interfaz.es_detectar(tecla):
                for modo in cams:
                    pendientes[modo], estados[modo] = None, ""
                    if frames[modo] is None:
                        continue
                    mensajes[modo], pend = procesar_ocr(frames[modo], zonas[modo], modo)
                    pendientes[modo] = pend
                    if pend and modo == "entrada":
                        estados[modo] = "E = guardar placa"
                    elif pend:  # salida: busca la tarifa de esa placa
                        _, estados[modo] = registro.consultar_salida(pend[0])
                        print("[salida] Tarifa:", estados[modo])

            elif interfaz.es_guardar(tecla) and "entrada" in cams:
                pend = pendientes["entrada"]
                if pend is None:
                    estados["entrada"] = "Primero detecta una placa (ESPACIO)"
                else:
                    _, estados["entrada"] = registro.registrar_placa(*pend)
                    print("[entrada] Registro:", estados["entrada"])
                    pendientes["entrada"] = None

            elif interfaz.es_dejar_salir(tecla) and "salida" in cams:
                pend = pendientes["salida"]
                if pend is None:
                    estados["salida"] = "Primero detecta una placa (ESPACIO)"
                else:
                    res, estados["salida"] = registro.registrar_salida(pend[0])
                    print("[salida] Salida:", estados["salida"])
                    if res != "pay":  # si debe pagar, vuelve a pulsar S cuando ya pagó
                        pendientes["salida"] = None

            elif interfaz.es_salir(tecla):
                break
    finally:
        for cam in cams.values():
            cam.cerrar()
        cv2.destroyAllWindows()
    print("Último texto leído:", ocr.obtener_texto())


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg and arg not in INDICES:
        raise SystemExit("Uso: python main.py [entrada | salida]  (sin argumento = las dos cámaras)")
    main((arg,) if arg else ("entrada", "salida"))
