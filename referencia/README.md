# Revisión de la base de datos de alexishh

`base_alexishh_original.sql` es el archivo tal como lo subió alexishh (commit `24b251a`, MySQL/MariaDB con
triggers y procedimientos). Esta carpeta solo lo conserva como referencia; la aplicación **no** lo usa.
El `base.sql` de la raíz es la versión unificada: el esquema de SmartPark (el que crea `models.py`) más lo
mejor de la base de alexishh.

## Por qué no se puede usar tal cual
- **Otro esquema:** tablas y columnas distintas (`sesiones`, `reservas`, `vehiculos`, `lugares`...) a las que
  usa la aplicación (`reservaciones`, `pagos`, `empleados`, `placas`). Usarla exigiría reescribir `models.py`,
  `logic.py`, el panel de administrador y las cámaras.
- **Otro nombre de base:** crea `smart_park`; la aplicación se conecta a `smartpark`.
- **Códigos de cajón distintos:** `A1` en lugar de `A01`.
- **Solo corre en MySQL/MariaDB** y con el cliente de línea de comandos o Workbench (usa `DELIMITER`); no se
  puede ejecutar desde Python/SQLAlchemy. Le falta el `DELIMITER ;` final.

## Lo que se tomó (ya en `base.sql` y `models.py`)
| Idea de alexishh | Cómo quedó en SmartPark |
|---|---|
| `UNIQUE (metodo_pago, referencia_transaccion)`: un folio no se cobra dos veces | `pagos` tiene `UNIQUE (method, ref)`; la pasarela genera folios que no se repiten (`new_folio`). Las bases antiguas reciben el índice al arrancar. |
| Tabla `lugares` con los 48 cajones y tipo `Normal`/`Accesible` | Tabla `lugares` (modelo `Spot`), con el primer cajón de cada área como Accesible. Además lleva `sensor_busy` y `sensor_at`, que usarán las ESP32. |

## Lo que conviene decidir (no se aplicó)
1. **Empleados con tarifa $0** (`categorias`: General $15, Trabajador $0). Hoy el panel solo avisa
   "revisar si aplica descuento". Es la mejora con más valor, pero cambia el cobro y las pantallas del boleto.
2. **Adeudo:** una salida sin pagar bloquea la siguiente entrada de esa placa. Con la pluma de salida que solo
   abre al pagar casi no ocurre; sirve si el administrador deja salir a alguien sin cobrar.
3. **Un solo vehículo activo por cajón y por placa a nivel de base de datos** (columnas generadas con índice
   único). Hoy lo garantiza el código Python; la base lo garantizaría aun con dos servidores a la vez.
4. **Triggers y procedimientos:** duplicarían la lógica de `logic.py` y chocan con el flujo actual (ver abajo).

## Problemas de su archivo (para hablarlo con él)
- **Depura la placa al pagar, no al salir.** `trg_pago_depuracion_placa` cierra la sesión (`Pagada`, con
  `hora_salida = NOW()`) y pone `placa = NULL` al registrar el pago. La cámara de salida ya no encuentra
  el vehículo, y se pierde el historial de quién estacionó.
- **No hay tolerancia ni cobro extra.** Tras pagar la sesión queda cerrada y `trg_pago_valida` rechaza más
  pagos: si el carro se queda una hora más, no se le puede cobrar. SmartPark da 15 min y cobra la diferencia.
- **Una reserva bloquea el cajón para siempre.** `lugar_reservado` es único mientras la reserva esté
  `Reservado`, sin importar la fecha ni la hora: un cajón no puede tener una reserva el lunes y otra el martes,
  y una reserva de mañana impide entrar hoy a ese cajón (`trg_entrada_general_vehiculo`).
- **Las reservas nunca vencen:** el script hace `DROP` de `sp_expirar_reservas` y `ev_expirar_reservas`,
  pero nunca los crea.
- **`penalizacion` no se usa** en ningún trigger ni procedimiento.
- **Falta la tarifa de reservación**, el estado de "apartado mientras se paga", el tipo de vehículo y el
  origen (web, cámara, admin).
- **`referencia_transaccion` guarda "UID del lector NFC".** El pago NFC va a ser simulado y no queremos
  guardar datos de una tarjeta real: conviene guardar solo un folio generado.
- No pude ejecutar su SQL en un servidor MySQL/MariaDB (no hay uno en este entorno): esta revisión es leyendo
  el código. Los índices únicos sobre columnas generadas `VIRTUAL` conviene probarlos en tu versión de MariaDB.
