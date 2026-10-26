"""Módulo de interfaz: dibujo en pantalla y lectura de teclas."""
import unicodedata
 
import cv2
import numpy as np
 
TECLA_ESPACIO = ord(' ')
TECLA_Q = ord('q')
TECLA_ESC = 27
TECLA_ENTER = 13
 
 
def _a_poligono(zona):
    """Convierte la zona a un arreglo (N, 1, 2) int32 que OpenCV puede dibujar.
 
    Acepta las 4 esquinas [[x, y], ...] o una caja (x, y, w, h).
    """
    zona = np.asarray(zona)
    if zona.shape == (4,):  # caja (x, y, w, h)
        x, y, w, h = zona
        zona = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])
    return zona.astype(np.int32).reshape(-1, 1, 2)
 
 
def dibujar_frame(frame, texto: str, zona=None, titulo: str = "OCR simple", estado: str = "", ayuda: str = "ESPACIO=detectar  ENTER=guardar  Q=salir"):
    """Dibuja las instrucciones, la zona de placa (4 esquinas) y el último texto."""
    display = frame.copy()
    if zona is not None:
        cv2.polylines(display, [_a_poligono(zona)], True, (0, 255, 255), 2)
    cv2.putText(display, ayuda, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    # La fuente de OpenCV no dibuja acentos: se quitan solo para mostrar
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    cv2.putText(display, texto[:80], (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    # Resultado del registro en la base de datos (amarillo)
    estado = unicodedata.normalize("NFKD", estado).encode("ascii", "ignore").decode()
    if estado:
        cv2.putText(display, estado[:80], (10, 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.imshow(titulo, display)
 
 
def leer_tecla() -> int:
    return cv2.waitKey(1) & 0xFF
 
 
def es_salir(tecla: int) -> bool:
    return tecla in (TECLA_Q, TECLA_ESC)
 
 
def es_detectar(tecla: int) -> bool:
    return tecla == TECLA_ESPACIO


def es_confirmar(tecla: int) -> bool:
    return tecla == TECLA_ENTER