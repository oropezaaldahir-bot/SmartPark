"""Módulo principal: orquesta cámara, OCR, interfaz y clasificación de placas.

Flujo:  ESPACIO -> detecta y lee la placa  |  ENTER -> la registra en la base de datos
        q / ESC -> salir
(Se pide confirmar con ENTER para no registrar una lectura equivocada del OCR.)
"""
import os

from modulos import camara
from modulos import ocr
from modulos import interfaz
from modulos import zona_placa
from modulos import detector_placa
from modulos import registro
from modulos.placas import extraer_placa

# Índice de la cámara: 0 = la de la computadora, 1 = externa. Cámbialo sin tocar el código:
#   (Windows)  set CAMARA_INDICE=0 && python main.py
CAMARA_INDICE = int(os.getenv("CAMARA_INDICE", "1"))


def main():
    ocr.iniciar_ocr()
    cap = camara.abrir_camara(indice=CAMARA_INDICE)

    mensaje = ""     # lo que se muestra en pantalla (placa reconocida)
    estado = ""      # resultado del registro en la base de datos
    pendiente = None  # (placa, tipo) leída y esperando ENTER
    print("ESPACIO -> detectar placa | ENTER -> registrar entrada | q / ESC -> salir")

    while True:
        ret, frame = camara.leer_frame(cap)
        if not ret:
            break
        # Localiza la placa automáticamente en cada frame (modelo YOLO entrenado)
        zona = detector_placa.detectar_zona_placa(frame)

        interfaz.dibujar_frame(frame, mensaje, zona, estado=estado)
        tecla = interfaz.leer_tecla()

        if interfaz.es_detectar(tecla):
            pendiente, estado = None, ""
            recorte = zona_placa.recortar_zona(frame, zona)
            if recorte is None:
                mensaje = "No se encontro ninguna placa en el frame"
                print("No se encontró ninguna zona de placa en el frame")
                continue

            ocr.detectar_texto(recorte)  # OCR solo dentro de la zona
            texto = ocr.obtener_texto()
            print("Texto detectado:", texto)

            # Elige del texto la parte que realmente es una placa
            placa, tipo = extraer_placa(texto)
            if placa:
                mensaje = f"{placa} - {tipo}"
                pendiente = (placa, tipo)
                estado = "ENTER = registrar entrada"
                print(f"Placa: {placa} | Tipo: {tipo}")
            else:
                mensaje = "Placa no reconocida"
                print("No se reconoció una placa válida en el texto")

        elif interfaz.es_confirmar(tecla):
            if pendiente is None:
                estado = "Primero detecta una placa (ESPACIO)"
            else:
                _, estado = registro.registrar_entrada(*pendiente)
                print("Registro:", estado)
                pendiente = None

        elif interfaz.es_salir(tecla):
            break

    camara.cerrar_camara(cap)
    print("Último texto guardado:", ocr.obtener_texto())


if __name__ == "__main__":
    main()
