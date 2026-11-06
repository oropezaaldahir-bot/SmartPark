CREATE DATABASE smart_park CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE smart_park;

SET FOREIGN_KEY_CHECKS = 0;


CREATE TABLE categorias (
    categoria     VARCHAR(30) NOT NULL,
    tarifa_hora   DECIMAL(10,2) NOT NULL DEFAULT 15.00,
    penalizacion  DECIMAL(10,2) NOT NULL DEFAULT 50.00,
    PRIMARY KEY (categoria)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- sin esto, cualquier INSERT en vehiculos falla
INSERT INTO categorias (categoria, tarifa_hora, penalizacion) VALUES
('General', 15.00, 50.00),
('Trabajador', 0.00, 0.00);

CREATE TABLE lugares (
    id_lugar        INT UNSIGNED NOT NULL AUTO_INCREMENT,
    codigo_espacio  VARCHAR(10) NOT NULL,
    tipo_lugar      ENUM('Normal','Accesible') NOT NULL DEFAULT 'Normal',
    PRIMARY KEY (id_lugar),
    UNIQUE KEY uk_codigo_espacio (codigo_espacio)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

INSERT INTO lugares (codigo_espacio, tipo_lugar) VALUES
('A1', 'Accesible'),
('A2', 'Normal'),
('A3', 'Normal'),
('A4', 'Normal'),
('A5', 'Normal'),
('A6', 'Normal'),
('A7', 'Normal'),
('A8', 'Normal'),
('B1', 'Accesible'),
('B2', 'Normal'),
('B3', 'Normal'),
('B4', 'Normal'),
('B5', 'Normal'),
('B6', 'Normal'),
('B7', 'Normal'),
('B8', 'Normal'),
('C1', 'Accesible'),
('C2', 'Normal'),
('C3', 'Normal'),
('C4', 'Normal'),
('C5', 'Normal'),
('C6', 'Normal'),
('C7', 'Normal'),
('C8', 'Normal'),
('D1', 'Accesible'),
('D2', 'Normal'),
('D3', 'Normal'),
('D4', 'Normal'),
('D5', 'Normal'),
('D6', 'Normal'),
('D7', 'Normal'),
('D8', 'Normal'),
('E1', 'Accesible'),
('E2', 'Normal'),
('E3', 'Normal'),
('E4', 'Normal'),
('E5', 'Normal'),
('E6', 'Normal'),
('E7', 'Normal'),
('E8', 'Normal'),
('F1', 'Accesible'),
('F2', 'Normal'),
('F3', 'Normal'),
('F4', 'Normal'),
('F5', 'Normal'),
('F6', 'Normal'),
('F7', 'Normal'),
('F8', 'Normal');

CREATE TABLE metodos_pago (
    metodo  VARCHAR(30) NOT NULL,
    PRIMARY KEY (metodo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

INSERT INTO metodos_pago (metodo) VALUES ('NFC'), ('Tarjeta');

CREATE TABLE vehiculos (
    placa           VARCHAR(15) NOT NULL,
    fecha_registro  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    categoria       VARCHAR(30) NOT NULL DEFAULT 'General',
    PRIMARY KEY (placa),
    KEY fk_vehiculos_categorias (categoria),
    CONSTRAINT fk_vehiculos_categorias
        FOREIGN KEY (categoria) REFERENCES categorias (categoria)
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE empleados (
    id_empleado  INT UNSIGNED NOT NULL AUTO_INCREMENT,
    nombre       VARCHAR(100) NOT NULL,
    placa        VARCHAR(15) NOT NULL,
    PRIMARY KEY (id_empleado),
    UNIQUE KEY uk_placa_empleado (placa),
    CONSTRAINT fk_empleados_vehiculos
        FOREIGN KEY (placa) REFERENCES vehiculos (placa)
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE reservas (
    codigo_reserva   VARCHAR(20) NOT NULL,
    placa            VARCHAR(15) DEFAULT NULL,
    id_lugar         INT UNSIGNED NOT NULL,
    fecha_reserva    DATE NOT NULL,
    hora_llegada     TIME NOT NULL,
    estado_reserva   ENUM('Reservado','Completada','Cancelada') NOT NULL DEFAULT 'Reservado',
    lugar_reservado  INT UNSIGNED GENERATED ALWAYS AS
                        (IF(estado_reserva = 'Reservado', id_lugar, NULL)) VIRTUAL,
    PRIMARY KEY (codigo_reserva),
    UNIQUE KEY uk_lugar_reservado (lugar_reservado),
    KEY fk_reservas_vehiculos (placa),
    KEY fk_reservas_lugares (id_lugar),
    CONSTRAINT fk_reservas_lugares
        FOREIGN KEY (id_lugar) REFERENCES lugares (id_lugar)
        ON UPDATE CASCADE,
    CONSTRAINT fk_reservas_vehiculos
        FOREIGN KEY (placa) REFERENCES vehiculos (placa)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE sesiones (
    id_sesion       INT UNSIGNED NOT NULL AUTO_INCREMENT,
    placa           VARCHAR(15) DEFAULT NULL,
    id_lugar        INT UNSIGNED NOT NULL,
    hora_entrada    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    hora_salida     DATETIME DEFAULT NULL,
    monto_total     DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    estado_sesion   ENUM('Activa','Pagada','Adeudo') NOT NULL DEFAULT 'Activa',
    lugar_activo    INT UNSIGNED GENERATED ALWAYS AS
                        (IF(estado_sesion = 'Activa', id_lugar, NULL)) VIRTUAL,
    placa_activa    VARCHAR(15) GENERATED ALWAYS AS
                        (IF(estado_sesion = 'Activa', placa, NULL)) VIRTUAL,
    PRIMARY KEY (id_sesion),
    UNIQUE KEY uk_lugar_activo (lugar_activo),
    UNIQUE KEY uk_placa_activa (placa_activa),
    KEY fk_sesiones_vehiculos (placa),
    KEY fk_sesiones_lugares (id_lugar),
    CONSTRAINT fk_sesiones_lugares
        FOREIGN KEY (id_lugar) REFERENCES lugares (id_lugar)
        ON UPDATE CASCADE,
    CONSTRAINT fk_sesiones_vehiculos
        FOREIGN KEY (placa) REFERENCES vehiculos (placa)
        ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE pagos (
    id_pago                  INT UNSIGNED NOT NULL AUTO_INCREMENT,
    id_sesion                INT UNSIGNED NOT NULL,
    metodo_pago               VARCHAR(30) NOT NULL,
    monto                     DECIMAL(10,2) NOT NULL,
    estado_pago               ENUM('Completado','Pendiente','Rechazado') NOT NULL DEFAULT 'Completado',
    referencia_transaccion    VARCHAR(100) NOT NULL COMMENT 'UID del lector NFC PN532 o folio bancario',
    fecha_hora_pago           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id_pago),
    -- Nuevo: sin esto, la misma referencia se podia reusar para cobrar dos veces.
    UNIQUE KEY uk_pagos_referencia (metodo_pago, referencia_transaccion),
    KEY fk_pagos_sesiones (id_sesion),
    KEY fk_pagos_metodos (metodo_pago),
    CONSTRAINT fk_pagos_metodos
        FOREIGN KEY (metodo_pago) REFERENCES metodos_pago (metodo)
        ON UPDATE CASCADE,
    CONSTRAINT fk_pagos_sesiones
        FOREIGN KEY (id_sesion) REFERENCES sesiones (id_sesion)
        ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

SET FOREIGN_KEY_CHECKS = 1;

-- Funcion, triggers y procedimientos

DROP FUNCTION IF EXISTS fn_monto_sesion;
DROP TRIGGER IF EXISTS trg_vehiculos_normaliza;
DROP TRIGGER IF EXISTS trg_empleados_alta;
DROP TRIGGER IF EXISTS trg_empleados_baja;
DROP TRIGGER IF EXISTS trg_reservas_alta;
DROP TRIGGER IF EXISTS trg_entrada_general_vehiculo;
DROP TRIGGER IF EXISTS trg_pago_valida;
DROP TRIGGER IF EXISTS trg_pago_depuracion_placa;
DROP PROCEDURE IF EXISTS sp_depurar_placa;
DROP PROCEDURE IF EXISTS sp_registrar_adeudo;
DROP PROCEDURE IF EXISTS sp_expirar_reservas;
DROP EVENT IF EXISTS ev_expirar_reservas;

DELIMITER $$

-- Calcula lo que se debe por una sesion, por hora iniciada, segun la
-- tarifa de la categoria del vehiculo (categorias.tarifa_hora).
CREATE FUNCTION fn_monto_sesion(p_id_sesion INT UNSIGNED, p_fin DATETIME)
RETURNS DECIMAL(10,2)
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_inicio DATETIME;
    DECLARE v_tarifa DECIMAL(10,2) DEFAULT 15.00;
    DECLARE v_horas INT DEFAULT 0;

    SELECT s.hora_entrada, COALESCE(c.tarifa_hora, 15.00)
      INTO v_inicio, v_tarifa
      FROM sesiones s
      LEFT JOIN vehiculos v ON v.placa = s.placa
      LEFT JOIN categorias c ON c.categoria = v.categoria
     WHERE s.id_sesion = p_id_sesion;

    SET v_horas = CEIL(TIMESTAMPDIFF(MINUTE, v_inicio, p_fin) / 60.0);
    IF v_horas < 0 THEN
        SET v_horas = 0;
    END IF;

    RETURN v_horas * v_tarifa;
END$$

-- Normaliza la placa (mayusculas, sin guiones ni espacios) al registrar
-- un vehiculo directamente.
CREATE TRIGGER trg_vehiculos_normaliza
BEFORE INSERT ON vehiculos
FOR EACH ROW
BEGIN
    SET NEW.placa = UPPER(REPLACE(REPLACE(NEW.placa, '-', ''), ' ', ''));
END$$

-- Alta de empleado: normaliza su placa y crea (o convierte) su vehiculo a
-- categoria 'Trabajador' (tarifa $0) ANTES del INSERT, para que la FK
-- hacia vehiculos ya encuentre la fila.
CREATE TRIGGER trg_empleados_alta
BEFORE INSERT ON empleados
FOR EACH ROW
BEGIN
    SET NEW.placa = UPPER(REPLACE(REPLACE(NEW.placa, '-', ''), ' ', ''));
    INSERT INTO vehiculos (placa, categoria) VALUES (NEW.placa, 'Trabajador')
        ON DUPLICATE KEY UPDATE categoria = 'Trabajador';
END$$

-- Baja de empleado: su vehiculo regresa a tarifa 'General'.
CREATE TRIGGER trg_empleados_baja
AFTER DELETE ON empleados
FOR EACH ROW
BEGIN
    UPDATE vehiculos SET categoria = 'General'
     WHERE placa = OLD.placa AND categoria = 'Trabajador';
END$$

-- Alta de reserva: normaliza la placa y crea el vehiculo si hace falta
-- (sin tocar su categoria si ya existia).
CREATE TRIGGER trg_reservas_alta
BEFORE INSERT ON reservas
FOR EACH ROW
BEGIN
    IF NEW.placa IS NOT NULL THEN
        SET NEW.placa = UPPER(REPLACE(REPLACE(NEW.placa, '-', ''), ' ', ''));
        INSERT IGNORE INTO vehiculos (placa) VALUES (NEW.placa);
    END IF;
END$$

-- Entrada (INSERT en sesiones): crea el vehiculo si hace falta, rechaza
-- la entrada si la placa tiene adeudo o si el lugar esta reservado por
-- otra placa, y si quien entra es el dueño de la reserva, la completa.
CREATE TRIGGER trg_entrada_general_vehiculo
BEFORE INSERT ON sesiones
FOR EACH ROW
BEGIN
    DECLARE v_adeudo INT DEFAULT 0;
    DECLARE v_reservado_otro INT DEFAULT 0;
    DECLARE v_mi_reserva VARCHAR(20) DEFAULT NULL;

    IF NEW.placa IS NOT NULL THEN
        SET NEW.placa = UPPER(REPLACE(REPLACE(NEW.placa, '-', ''), ' ', ''));
        INSERT IGNORE INTO vehiculos (placa) VALUES (NEW.placa);

        SELECT COUNT(*) INTO v_adeudo
          FROM sesiones
         WHERE placa = NEW.placa AND estado_sesion = 'Adeudo';

        IF v_adeudo > 0 THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Entrada rechazada: la placa tiene un adeudo pendiente.';
        END IF;
    END IF;

    SELECT COUNT(*) INTO v_reservado_otro
      FROM reservas r
     WHERE r.lugar_reservado = NEW.id_lugar
       AND NOT (r.placa IS NOT NULL AND NEW.placa IS NOT NULL AND r.placa = NEW.placa);

    IF v_reservado_otro > 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'Entrada rechazada: el lugar esta reservado.';
    END IF;

    IF NEW.placa IS NOT NULL THEN
        SELECT codigo_reserva INTO v_mi_reserva
          FROM reservas
         WHERE id_lugar = NEW.id_lugar
           AND placa = NEW.placa
           AND estado_reserva = 'Reservado'
         LIMIT 1;

        IF v_mi_reserva IS NOT NULL THEN
            UPDATE reservas SET estado_reserva = 'Completada'
             WHERE codigo_reserva = v_mi_reserva;
        END IF;
    END IF;
END$$

-- Antes de aceptar un pago 'Completado', verifica que la sesion siga
-- 'Activa' o en 'Adeudo'. Evita cobrar dos veces la misma sesion.
CREATE TRIGGER trg_pago_valida
BEFORE INSERT ON pagos
FOR EACH ROW
BEGIN
    DECLARE v_estado VARCHAR(10) DEFAULT NULL;

    IF NEW.estado_pago = 'Completado' THEN
        SELECT estado_sesion INTO v_estado
          FROM sesiones
         WHERE id_sesion = NEW.id_sesion;

        IF v_estado IS NOT NULL AND v_estado NOT IN ('Activa', 'Adeudo') THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Pago rechazado: la sesion ya esta pagada.';
        END IF;
    END IF;
END$$

-- Al completar un pago: fija hora_salida y el monto (si la sesion seguia
-- 'Activa'), la pasa a 'Pagada' y depura la placa.
CREATE TRIGGER trg_pago_depuracion_placa
AFTER INSERT ON pagos
FOR EACH ROW
BEGIN
    DECLARE v_placa VARCHAR(15);
    DECLARE v_fin DATETIME;
    DECLARE v_monto DECIMAL(10,2);

    IF NEW.estado_pago = 'Completado' THEN
        SELECT placa, IFNULL(hora_salida, NOW()) INTO v_placa, v_fin
          FROM sesiones
         WHERE id_sesion = NEW.id_sesion;

        SET v_monto = fn_monto_sesion(NEW.id_sesion, v_fin);

        UPDATE sesiones
           SET hora_salida = IFNULL(hora_salida, v_fin),
               monto_total = IF(estado_sesion = 'Activa', v_monto, monto_total),
               estado_sesion = 'Pagada'
         WHERE id_sesion = NEW.id_sesion;

        IF v_placa IS NOT NULL THEN
            CALL sp_depurar_placa(v_placa);
        END IF;
    END IF;
END$$

-- Depura una placa: la borra de vehiculos SALVO que sea de un empleado,
-- tenga un adeudo, una sesion activa o una reserva viva.
CREATE PROCEDURE sp_depurar_placa(IN p_placa VARCHAR(15))
BEGIN
    DECLARE v_es_empleado INT DEFAULT 0;
    DECLARE v_adeudos INT DEFAULT 0;
    DECLARE v_activas INT DEFAULT 0;
    DECLARE v_reservas_vivas INT DEFAULT 0;

    IF p_placa IS NOT NULL THEN
        SELECT COUNT(*) INTO v_es_empleado FROM empleados WHERE placa = p_placa;

        SELECT COUNT(*) INTO v_adeudos
          FROM sesiones WHERE placa = p_placa AND estado_sesion = 'Adeudo';

        SELECT COUNT(*) INTO v_activas
          FROM sesiones WHERE placa = p_placa AND estado_sesion = 'Activa';

        SELECT COUNT(*) INTO v_reservas_vivas
          FROM reservas WHERE placa = p_placa AND estado_reserva = 'Reservado';

        IF v_es_empleado = 0 AND v_adeudos = 0
           AND v_activas = 0 AND v_reservas_vivas = 0 THEN
            UPDATE sesiones SET placa = NULL WHERE placa = p_placa;
            DELETE FROM vehiculos WHERE placa = p_placa;
        END IF;
    END IF;
END$$

-- Salida sin pagar: calcula el monto y cierra la sesion. Si el monto es
-- $0 (tipicamente un empleado) cierra directo como 'Pagada', no 'Adeudo'.
CREATE PROCEDURE sp_registrar_adeudo(IN p_id_sesion INT UNSIGNED)
BEGIN
    DECLARE v_fin DATETIME DEFAULT NOW();
    DECLARE v_monto DECIMAL(10,2) DEFAULT 0.00;
    DECLARE v_placa VARCHAR(15) DEFAULT NULL;
    DECLARE v_filas INT DEFAULT 0;

    SET v_monto = fn_monto_sesion(p_id_sesion, v_fin);

    UPDATE sesiones
       SET hora_salida = v_fin,
           monto_total = v_monto,
           estado_sesion = IF(v_monto = 0, 'Pagada', 'Adeudo')
     WHERE id_sesion = p_id_sesion AND estado_sesion = 'Activa';

    SET v_filas = ROW_COUNT();

    IF v_filas > 0 AND v_monto = 0 THEN
        SELECT placa INTO v_placa FROM sesiones WHERE id_sesion = p_id_sesion;
        IF v_placa IS NOT NULL THEN
            CALL sp_depurar_placa(v_placa);
        END IF;
    END IF;
END$$
