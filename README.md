# SmartPark (Python + SQL)

Toda la lógica que estaba en JavaScript ahora corre en **Python (Flask)** y los datos viven en una **base SQL**.
Las páginas se generan en el servidor (plantillas Jinja) y **no usan JavaScript**.

## Ejecutar
```
pip install -r requirements.txt
python app.py            # http://localhost:5000
python -m pytest -q      # pruebas
```
La primera vez crea las tablas y carga 8 vehículos DEMO.

## Rutas
| Ruta | Qué es |
|---|---|
| `/acceso` | Entrada por placa (solo placas que la cámara ya guardó, con reserva o de empleados) |
| `/boleto` | Boleto, pago en línea y descarga PNG |
| `/reservar` | Reservación con tarifa por día y hora |
| `/pasarela/` | Pasarela de pago **simulada** |
| `/admin/login`, `/admin/` | Panel de administrador |

Administrador por defecto: `admin` / `smartpark2026`. Cámbialos con las variables
`ADMIN_USER` y `ADMIN_PASS` (o `ADMIN_PASS_HASH`, generado con `werkzeug.security.generate_password_hash`).

## Cámaras: entrada y salida (main.py)
Se usan **dos cámaras**, cada una en su propia terminal, con la misma base de datos:

```
pip install -r requirements.txt -r requirements-camara.txt
python main.py entrada     # ESPACIO = detectar placa · ENTER = guardarla en la base · q / ESC = salir
python main.py salida      # ESPACIO = detectar y buscar la tarifa · ENTER = dejar salir (solo si ya pagó)
```
- **Entrada:** detecta la placa y la **guarda** en la tabla `placas`. En `/acceso` solo se deja entrar a una placa
  si está en la base (guardada por la cámara, con reserva vigente o de empleado); si no, "Placa no registrada".
- **Salida:** detecta la placa, busca el vehículo dentro y **muestra la tarifa** ($15 por hora iniciada). Si no ha pagado
  no lo deja salir ("debe pagar $X"); se paga en el boleto (pasarela simulada) o en efectivo con el administrador y se
  pulsa ENTER otra vez. Al salir se registra la salida y se **elimina la placa** de `placas` (la visita y los pagos
  se conservan en el historial). Para volver a entrar, la cámara de entrada tiene que guardarla de nuevo.
  También se borra si la salida la registra el administrador.
- Índices de cámara (0 = la de la computadora, 1 = externa): `CAMARA_ENTRADA` (por defecto 0) y `CAMARA_SALIDA`
  (por defecto 1). Windows: `set CAMARA_ENTRADA=0` y `set CAMARA_SALIDA=1`; PowerShell: `$env:CAMARA_SALIDA="1"`.
- Corre `python app.py` y las dos cámaras con el mismo `DATABASE_URL` (con SQLite basta ejecutarlos desde esta carpeta).
- `modelos/placa.pt` es tu detector entrenado; `yolov8n.pt` es el modelo base para volver a entrenar
  (`python -m modulos.detector_placa entrenar banco`).
- Se pide confirmar con ENTER para no usar una lectura equivocada del OCR.
- Si la base no responde, la cámara no se cierra: muestra "No se pudo guardar en la base de datos".

## Gráfica del administrador
Muestra las entradas reales de los últimos 7 días: cada vehículo que entra suma 1 en la barra de su día.

## Base de datos SQL
Por defecto usa SQLite (`smartpark.db`). Para MySQL, PostgreSQL o SQL Server, define `DATABASE_URL`
(ejemplos en `config.py`; el conector va en `requirements.txt`) e instala el conector. Tablas: `reservaciones`, `pagos`, `empleados`, `placas`
(SQL puro en `base.sql`).

## Archivos
- `main.py` + `modulos/` + `modelos/` reconocimiento de placas con cámara (ver abajo)
- `base.sql` esquema SQL · `config.py` ajustes y áreas · `models.py` tablas · `logic.py` reglas (tarifas, cobro, estados, código de barras)
- `app.py` clientes · `pasarela.py` pago simulado · `admin.py` panel · `ticket_png.py` boleto/recibo en imagen
- `templates/` HTML · `static/` CSS · `tests/` pruebas

## Pagos y datos de tarjeta
- Se guarda **solo** método, monto y folio. Nunca número, vencimiento, CVV ni últimos dígitos.
- La pasarela es una simulación: valida el formato y descarta los datos. Para cobrar de verdad, reemplaza
  `pasarela.py` por Mercado Pago, Stripe o Conekta (la tarjeta se captura en su sitio, no en tu servidor).
- Tarifa de reservación: función `reservation_fee` en `logic.py`.

## Para producción
Con una base real usa `SEED_DEMO=0` para no cargar los vehículos DEMO. Define `SECRET_KEY` y la contraseña del admin con variables de entorno, usa HTTPS y un servidor
como gunicorn/waitress en lugar de `app.run`. El bloqueo de intentos del login está en memoria.

## Qué cambió respecto a la versión JS
Sin JavaScript, la cuenta regresiva en vivo se sustituye por recarga automática cada 20–30 s (boleto y
reserva), el panel admin tiene el enlace "↻ Actualizar", los avisos desaparecen solos con CSS y las
confirmaciones son una pantalla aparte. A cambio, los datos ya son compartidos entre dispositivos.
