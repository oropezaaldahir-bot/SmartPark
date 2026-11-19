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
Las **dos cámaras USB corren a la vez en un solo programa** (cada una en su hilo y su ventana), con la misma base de datos:

```
pip install -r requirements.txt -r requirements-camara.txt
python main.py             # las dos cámaras
python main.py entrada     # solo la de entrada
python main.py salida      # solo la de salida
```
Teclas: **ESPACIO** = leer la placa en las cámaras abiertas · **E** = (entrada) guardar la placa en la base ·
**S** = (salida) dejar salir, solo si ya pagó · **q / ESC** = salir.

- **Entrada:** detecta la placa y la **guarda** en la tabla `placas`. En `/acceso` solo se deja entrar a una placa
  si está en la base (guardada por la cámara, con reserva vigente o de empleado); si no, "Placa no registrada".
- **Salida:** detecta la placa, busca el vehículo dentro y **muestra la tarifa** ($15 por hora iniciada). Si no ha pagado
  no lo deja salir ("debe pagar $X"); se paga en el boleto (pasarela simulada) o en efectivo con el administrador y se
  pulsa S otra vez. Al salir se registra la salida y se **elimina la placa** de `placas` (la visita y los pagos
  se conservan en el historial). Para volver a entrar, la cámara de entrada tiene que guardarla de nuevo.
  También se borra si la salida la registra el administrador.
- Índice USB de cada cámara: `CAMARA_ENTRADA` (por defecto 0) y `CAMARA_SALIDA` (por defecto 1). Windows: `set CAMARA_ENTRADA=0` y `set CAMARA_SALIDA=1`; PowerShell: `$env:CAMARA_SALIDA="1"`.
- Corre `python app.py` y las dos cámaras con el mismo `DATABASE_URL` (con SQLite basta ejecutarlos desde esta carpeta).
- `modelos/placa.pt` es tu detector entrenado; `yolov8n.pt` es el modelo base para volver a entrenar
  (`python -m modulos.detector_placa entrenar banco`).
- Se pide confirmar con E / S para no usar una lectura equivocada del OCR.
- Si la base no responde, la cámara no se cierra: muestra "No se pudo guardar en la base de datos".

## ESP32 de la maqueta (WiFi + API)
Las dos ESP32 hablan con Flask por WiFi (HTTP + JSON). Sketches en `esp32/entrada/entrada.ino` y `esp32/salida/salida.ino`
(librerías: ArduinoJson 7.x, Adafruit GFX, Adafruit ST7735 and ST7789, Adafruit PN532).

1. La PC y las ESP32 en la **misma red WiFi** (2.4 GHz). Dale a la PC una IP fija o reservada en el router (ej. `192.168.1.50`)
   y pon esa IP, el WiFi y la clave de API en la parte de arriba de cada sketch.
2. `python app.py` ahora escucha en `0.0.0.0:5000` (antes solo `localhost`). El modo debug ya no va por defecto
   (deja un depurador abierto a la red): actívalo con `FLASK_DEBUG=1`. En Windows, permite el puerto 5000 en el firewall.
3. Cambia la clave con `ESP32_TOKEN` (igual en los sketches, constante `API_KEY`). Los cajones con sensor son los de
   `ESP32_SPOTS` (por defecto `A01,A02,A03,A04`, en el orden de los 4 sensores).

| Ruta (todas piden el encabezado `X-API-Key`) | Qué hace |
|---|---|
| `POST /api/entrada/estado` `{"cajones":[true,false,...]}` | La ESP32 de entrada reporta sus cajones; se guardan en `lugares.sensor_busy` |
| `POST /api/entrada/vehiculo` | Llegó un carro: pide la lectura a la cámara y, cuando la placa ya está leída, registra la entrada y responde `abrir: true` + el cajón |
| `POST /api/salida/vehiculo` | Hay un carro en la salida: pide a la cámara de salida que lea la placa |
| `POST /api/salida/nfc` `{"uid":"04A1B2C3"}` | Se pasó la tarjeta: cobra (simulado), registra la salida y responde `autorizado: true/false` |

**Lectura de placa automática (sin teclas).** Cuando el sensor de una ESP32 ve un carro, le pide a Flask que la cámara de
ese lado lea la placa: la API anota una solicitud en la tabla `solicitudes_camara` (caduca a los `SOLICITUD_TTL` = 10 s y la
ESP32 la renueva mientras el carro espera) y `main.py` la atiende solo. Para no usar un OCR equivocado, la **misma placa debe
leerse 2 veces seguidas** (hasta 12 lecturas, `COINCIDENCIAS` / `INTENTOS_AUTO` en `main.py`); si no se logra, la ESP32 vuelve a pedirla.
- **Entrada:** el carro llega al sensor → la cámara lee y guarda la placa → la ESP32 (que pregunta cada segundo) recibe `abrir: true` + el cajón.
- **Salida:** el carro llega al sensor → la cámara lee la placa y busca la tarifa → pasar la tarjeta NFC cobra, abre y registra la salida.
- Las teclas siguen funcionando como respaldo (ESPACIO / E / S). Si la lectura es manual, hazla con el carro ya frente al sensor:
  al llegar un carro nuevo la ESP32 descarta cualquier lectura vieja (`"nuevo": true`).

La placa leída queda en la tabla `lecturas_camara`; cada lectura se usa **una sola vez** y caduca a los `LECTURA_TTL` segundos (120).
La seguridad antiatropello se queda en la ESP32 y no se hacen llamadas de red mientras la pluma se mueve.

## Empleados
Las placas que registra el administrador en "Empleados" no pagan el estacionamiento (tarifa de empleado $0;
cámbiala con `RATE_EMPLEADO`). Entran, salen y se ven en el boleto como "Tarifa de empleado" sin pasar por la pasarela.
Si se da de baja a un empleado que está dentro, su estancia se cobra completa a la tarifa normal.
La tarifa de reservación se cobra igual a todos.

## Gráfica del administrador
Muestra las entradas reales de los últimos 7 días: cada vehículo que entra suma 1 en la barra de su día.

## Base de datos SQL
Por defecto usa SQLite (`smartpark.db`). Para MySQL, PostgreSQL o SQL Server, define `DATABASE_URL`
(ejemplos en `config.py`; el conector va en `requirements.txt`) e instala el conector. Tablas: `reservaciones`, `pagos`, `empleados`, `placas`, `lugares`. La base de alexishh (MySQL con triggers) está en `referencia/` con su revisión
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
