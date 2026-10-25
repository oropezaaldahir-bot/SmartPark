-- base.sql · Base de datos de SmartPark en SQL estándar.
-- La aplicación crea estas tablas sola (db.create_all) y agrega las columnas nuevas si faltan,
-- así que este archivo es opcional: úsalo para crear la base a mano o integrarla a tu repositorio.
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
    ref              VARCHAR(20) NULL
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

-- Si ya tenías la tabla de una versión anterior, agrega las columnas nuevas:
--   ALTER TABLE reservaciones ADD COLUMN vehicle_type VARCHAR(12);
--   ALTER TABLE reservaciones ADD COLUMN source VARCHAR(10);
