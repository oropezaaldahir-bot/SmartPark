"""Módulo de cámara: apertura, lectura y cierre."""
import cv2
import threading
import time


class CamaraHilo:
    """Lee una cámara en un hilo propio y guarda siempre el frame más reciente."""

    def __init__(self, indice: int, ancho: int = 1280, alto: int = 720):
        self.cap = abrir_camara(indice, ancho, alto)
        self._lock = threading.Lock()
        self._ok, self._frame = False, None
        self._activo = True
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def _bucle(self):
        while self._activo:
            ok, frame = self.cap.read()
            with self._lock:
                self._ok, self._frame = ok, frame
            if not ok:
                time.sleep(0.05)  # cámara sin imagen: no gastar CPU en el hilo

    def leer(self):
        """Devuelve (ok, copia_del_frame_más_reciente)."""
        with self._lock:
            if not self._ok or self._frame is None:
                return False, None
            return True, self._frame.copy()

    def cerrar(self):
        self._activo = False
        self._hilo.join(timeout=1)
        self.cap.release()


def abrir_camara(indice: int = 1, ancho: int = 1280, alto: int = 720):
    """Abre la cámara y devuelve el objeto VideoCapture."""
    cap = cv2.VideoCapture(indice)  # 0 = cámara por defecto
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)

    if not cap.isOpened():
        raise RuntimeError("No se pudo abrir la cámara")
    return cap


def leer_frame(cap):
    """Devuelve (ok, frame) de la cámara."""
    return cap.read()


def cerrar_camara(cap):
    """Libera la cámara y cierra las ventanas."""
    cap.release()
    cv2.destroyAllWindows()
