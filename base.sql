-- base.sql · Base de datos de SmartPark en SQL estándar.
-- La aplicación crea estas tablas sola (db.create_all) y agrega las columnas nuevas si faltan,
-- así que este archivo es opcional: úsalo para crear la base a mano o integrarla a tu repositorio.
--
-- Nota: la base.sql que subió alexishh (MySQL con triggers y procedimientos) se conserva en
--       referencia/base_alexishh_original.sql; ver referencia/README.md para lo que se tomó de ella.
--
-- 1) Crea la base (elige tu motor; con SQLite no hace falta):
--      MySQL / MariaDB:  CREATE DATABASE IF NOT EXISTS smartpark CHARACTER SET utf8mb4;  USE smartpark;
--      PostgreSQL:       CREATE DATABASE smartpark;   (y conéctate a ella)
--      SQL Server:       CREATE DATABASE smartpark;   USE smartpark;
-- 2) Ejecuta lo de abajo. En SQL Server cambia VARCHAR por NVARCHAR y BOOLEAN por BIT;
--    en MySQL usa AUTO_INCREMENT, en PostgreSQL SERIAL y en SQL Server IDENTITY para "id".

CREATE TABLE IF NOT EXISTS reservaciones (
    code         VARCHAR(10) PRIMARY KEY,         -- SP-1234
    plate        VARCHAR(10) NOT NULL,            -- ABC-123
    spot         VARCHAR(3)  NOT NULL,            -- A01 .. F08
    start        TIMESTAMP   NOT NULL,            -- llegada prevista
    checkin      TIMESTAMP   NULL,                -- entrada real
    exit_at      TIMESTAMP   NULL,                -- salida
    status       VARCHAR(10) NOT NULL,            -- hold | reserved | in | done | cancelled | expired
    hold_until   TIMESTAMP   NULL,                -- el cajón se aparta mientras se paga
    walkin       BOOLEAN     NOT NULL DEFAULT FALSE,
    vehicle_type VARCHAR(12) NULL,                -- Automóvil | Motocicleta | Camión (lo detecta la cámara)
    source       VARCHAR(10) NULL,                -- web | camara | admin
    fee_amount   INTEGER     NULL,                -- tarifa de reservación pagada
    fee_at       TIMESTAMP   NULL,
    fee_method   VARCHAR(10) NULL,                -- tarjeta | efectivo
    fee_ref      VARCHAR(20) NULL                 -- folio de la pasarela (nunca datos de tarjeta)
);
CREATE INDEX ix_reservaciones_spot   ON reservaciones (spot);
CREATE INDEX ix_reservaciones_status ON reservaciones (status);

CREATE TABLE IF NOT EXISTS pagos (
    id               INTEGER PRIMARY KEY,
    reservation_code VARCHAR(10) NOT NULL REFERENCES reservaciones (code),
    at               TIMESTAMP   NOT NULL,
    amount           INTEGER     NOT NULL,
    method           VARCHAR(10) NOT NULL,        -- tarjeta | efectivo
    ref              VARCHAR(20) NULL,
    CONSTRAINT uk_pagos_metodo_ref UNIQUE (method, ref)   -- un folio no se usa dos veces (el efectivo no lleva folio)
);
CREATE INDEX ix_pagos_reservation_code ON pagos (reservation_code);

CREATE TABLE IF NOT EXISTS empleados (
    id          INTEGER PRIMARY KEY,
    name        VARCHAR(40) NOT NULL,
    plate       VARCHAR(10) NOT NULL,             -- ABC-123
    plate_norm  VARCHAR(10) NOT NULL UNIQUE       -- ABC123
);

-- Placas que la cámara detectó y guardó: solo estas (más reservas y empleados) pueden entrar por /acceso
CREATE TABLE IF NOT EXISTS placas (
    id            INTEGER PRIMARY KEY,
    plate         VARCHAR(10) NOT NULL,           -- ABC-123
    plate_norm    VARCHAR(10) NOT NULL UNIQUE,    -- ABC123
    vehicle_type  VARCHAR(12) NULL,               -- Automóvil | Motocicleta | Camión
    first_seen    TIMESTAMP   NOT NULL,
    last_seen     TIMESTAMP   NOT NULL,
    hits          INTEGER     NOT NULL DEFAULT 1  -- veces que la cámara la detectó
);

-- Los 48 cajones. sensor_busy queda en NULL en los cajones sin sensor; los que tienen sensor (ESP32)
-- lo actualizan: 1 = ocupado, 0 = libre.
CREATE TABLE IF NOT EXISTS lugares (
    code         VARCHAR(3)  PRIMARY KEY,         -- A01 .. F08
    area         VARCHAR(1)  NOT NULL,
    kind         VARCHAR(10) NOT NULL DEFAULT 'Normal',   -- Normal | Accesible
    sensor_busy  BOOLEAN     NULL,
    sensor_at    TIMESTAMP   NULL
);
CREATE INDEX ix_lugares_area ON lugares (area);

INSERT INTO lugares (code, area, kind) VALUES
('A01', 'A', 'Accesible'),
('A02', 'A', 'Normal'),
('A03', 'A', 'Normal'),
('A04', 'A', 'Normal'),
('A05', 'A', 'Normal'),
('A06', 'A', 'Normal'),
('A07', 'A', 'Normal'),
('A08', 'A', 'Normal'),
('B01', 'B', 'Accesible'),
('B02', 'B', 'Normal'),
('B03', 'B', 'Normal'),
('B04', 'B', 'Normal'),
('B05', 'B', 'Normal'),
('B06', 'B', 'Normal'),
('B07', 'B', 'Normal'),
('B08', 'B', 'Normal'),
('C01', 'C', 'Accesible'),
('C02', 'C', 'Normal'),
('C03', 'C', 'Normal'),
('C04', 'C', 'Normal'),
('C05', 'C', 'Normal'),
('C06', 'C', 'Normal'),
('C07', 'C', 'Normal'),
('C08', 'C', 'Normal'),
('D01', 'D', 'Accesible'),
('D02', 'D', 'Normal'),
('D03', 'D', 'Normal'),
('D04', 'D', 'Normal'),
('D05', 'D', 'Normal'),
('D06', 'D', 'Normal'),
('D07', 'D', 'Normal'),
('D08', 'D', 'Normal'),
('E01', 'E', 'Accesible'),
('E02', 'E', 'Normal'),
('E03', 'E', 'Normal'),
('E04', 'E', 'Normal'),
('E05', 'E', 'Normal'),
('E06', 'E', 'Normal'),
('E07', 'E', 'Normal'),
('E08', 'E', 'Normal'),
('F01', 'F', 'Accesible'),
('F02', 'F', 'Normal'),
('F03', 'F', 'Normal'),
('F04', 'F', 'Normal'),
('F05', 'F', 'Normal'),
('F06', 'F', 'Normal'),
('F07', 'F', 'Normal'),
('F08', 'F', 'Normal');

-- Si ya tenías la tabla de una versión anterior, agrega las columnas nuevas:
--   ALTER TABLE reservaciones ADD COLUMN vehicle_type VARCHAR(12);
--   ALTER TABLE reservaciones ADD COLUMN source VARCHAR(10);
