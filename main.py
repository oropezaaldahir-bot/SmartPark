"""Módulo principal: orquesta cámara, OCR, interfaz y clasificación de placas.

Se corre una vez por cámara (dos ventanas, dos terminales):

    python main.py entrada   ESPACIO = detecta la placa | ENTER = la GUARDA en la base de datos
    python main.py salida    ESPACIO = detecta la placa y busca su tarifa
                             ENTER   = deja salir SOLO si ya pagó; registra la salida y borra la placa

q / ESC -> salir. Se pide confirmar con ENTER para no usar una lectura equivocada del OCR.
"""
import os
import sys

from modulos import camara
from modulos import ocr
from modulos import interfaz
from modulos import zona_placa
from modulos import detector_placa
from modulos import registro
from modulos.placas import extraer_placa

# Índice de cada cámara: 0 = la de la computadora, 1 = externa, etc. Cámbialos sin tocar el código:
#   (Windows)  set CAMARA_ENTRADA=0 && set CAMARA_SALIDA=1 && python main.py entrada
CAMARA_ENTRADA = int(os.getenv("CAMARA_ENTRADA", os.getenv("CAMARA_INDICE", "0")))
CAMARA_SALIDA = int(os.getenv("CAMARA_SALIDA", "1"))

MODOS = {
    "entrada": dict(titulo="Camara de ENTRADA", ayuda="ESPACIO=detectar  ENTER=guardar placa  Q=salir"),
    "salida": dict(titulo="Camara de SALIDA", ayuda="ESPACIO=detectar y cobrar  ENTER=dejar salir  Q=salir"),
}


def main(modo="entrada"):
    if modo not in MODOS:
        raise SystemExit("Uso: python main.py entrada | salida")
    cfg = MODOS[modo]
    ocr.iniciar_ocr()
    cap = camara.abrir_camara(indice=CAMARA_ENTRADA if modo == "entrada" else CAMARA_SALIDA)

    mensaje = ""     # lo que se muestra en pantalla (placa reconocida)
    estado = ""      # resultado en la base de datos
    pendiente = None  # (placa, tipo) leída y esperando ENTER
    print(f"[{modo.upper()}] {cfg['ayuda']}")

    while True:
        ret, frame = camara.leer_frame(cap)
        if not ret:
            break
        # Localiza la placa automáticamente en cada frame (modelo YOLO entrenado)
        zona = detector_placa.detectar_zona_placa(frame)

        interfaz.dibujar_frame(frame, mensaje, zona, titulo=cfg["titulo"], estado=estado, ayuda=cfg["ayuda"])
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
                print(f"Placa: {placa} | Tipo: {tipo}")
                if modo == "entrada":
                    estado = "ENTER = guardar placa"
                else:  # busca la tarifa de esa placa
                    _, estado = registro.consultar_salida(placa)
                    print("Tarifa:", estado)
            else:
                mensaje = "Placa no reconocida"
                print("No se reconoció una placa válida en el texto")

        elif interfaz.es_confirmar(tecla):
            if pendiente is None:
                estado = "Primero detecta una placa (ESPACIO)"
            elif modo == "entrada":
                _, estado = registro.registrar_placa(*pendiente)
                print("Registro:", estado)
                pendiente = None
            else:
                res, estado = registro.registrar_salida(pendiente[0])
                print("Salida:", estado)
                if res != "pay":  # si debe pagar, ENTER de nuevo cuando ya pagó
                    pendiente = None

        elif interfaz.es_salir(tecla):
            break

    camara.cerrar_camara(cap)
    print("Último texto leído:", ocr.obtener_texto())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "entrada")
