// ====================================================================
// SMARTPARK · ESP32 #2 · MÓDULO DE SALIDA (WiFi + Flask)
//
// Flujo:
//   1. El sensor ve un carro en la salida (< 15 cm).
//   2. La cámara de salida (main.py, tecla ESPACIO) lee la placa y la deja para esta barrera.
//   3. Pasan la tarjeta NFC  ->  POST /api/salida/nfc  {"uid": "..."}
//      Flask cobra (pago simulado), registra la salida y responde autorizado true/false.
//   4. Si autorizó: abre, espera a que el carro pase, cierra (y reabre si algo se atraviesa).
//
// Mientras la barrera se mueve NO se hace ninguna llamada de red.
//
// Librerías: ArduinoJson 7.x, Adafruit PN532  (WiFi y HTTPClient ya vienen con el ESP32)
// ====================================================================
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_PN532.h>

// ===================== AJUSTA ESTO =====================
const char* WIFI_SSID = "TU_WIFI";
const char* WIFI_PASS = "TU_CLAVE";
const char* SERVER    = "http://192.168.1.50:5000";  // IP de tu PC (donde corre app.py)
const char* API_KEY   = "smartpark-esp32";           // igual que ESP32_TOKEN en Flask (config.py)
// =======================================================

// 1. LECTOR NFC PN532 (I2C: SDA = 21, SCL = 22). Se dejan IRQ/RESET como los tenías porque así te funciona.
#define PN532_IRQ   (2)
#define PN532_RESET (3)
Adafruit_PN532 nfc(PN532_IRQ, PN532_RESET);

// 2. SENSOR ULTRASÓNICO HC-SR04
const int trigPin = 5;
const int echoPin = 18;   // ~3.3 V desde el divisor (1k + 2.2k)

// 3. PUENTE H TB6612FNG
const int STBY = 19;
const int PWMA = 23;
const int AIN1 = 25;      // abrir
const int AIN2 = 26;      // cerrar

// ---------- umbrales y tiempos ----------
const float UMBRAL_VEHICULO = 15.0;                // cm
const int   VELOCIDAD       = 220;                 // PWM 0-255
const unsigned long T_ABRIR_MS      = 2000;        // ajusta al recorrido de tu pluma
const unsigned long T_CERRAR_MS     = 2000;
const unsigned long T_REABRIR_MS    = 1500;
const unsigned long T_DESPEJADO_MS  = 1000;        // el sensor debe verse libre este tiempo antes de cerrar
const unsigned long VENTANA_NFC_MS  = 30000;       // tiempo para pasar la tarjeta (incluye leer la placa en la cámara)
const unsigned long PERIODO_SENSOR  = 50;
const unsigned long T_ULTRA_US      = 8000;        // timeout del eco (~137 cm)

// ---------- máquina de estados ----------
enum Estado { REPOSO, ESPERANDO_NFC, ABRIENDO, ESPERANDO_PASO, CERRANDO, REABRIENDO, ENFRIAR };
Estado estado = REPOSO;
unsigned long tEstado = 0;
unsigned long tSensor = 0, tReporte = 0, tWifi = 0, tProximaLectura = 0;
unsigned long tDespejado = 0, tLibreReposo = 0, tAusente = 0;
float dist = 999;
int   presencia = 0;
bool  puedeDetectar = true;

void cambiar(Estado e) { estado = e; tEstado = millis(); }

// =====================================================================
float medirDistancia() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  long dur = pulseIn(echoPin, HIGH, T_ULTRA_US);
  if (dur == 0) return 999.0;
  return dur * 0.034 / 2.0;
}
bool hayVehiculo(float d) { return d > 0.5 && d < UMBRAL_VEHICULO; }

void motorAbrir() {
  digitalWrite(STBY, HIGH);
  analogWrite(PWMA, VELOCIDAD);
  digitalWrite(AIN1, HIGH);
  digitalWrite(AIN2, LOW);
}
void motorCerrar() {
  digitalWrite(STBY, HIGH);
  analogWrite(PWMA, VELOCIDAD);
  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, HIGH);
}
void motorParar(bool reposo) {
  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, LOW);
  if (reposo) digitalWrite(STBY, LOW);
}

// =====================================================================
void wifiMantener() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - tWifi < 10000) return;
  tWifi = millis();
  Serial.println("[WIFI] Sin conexión, reintentando...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

int postJson(const char* ruta, const String& cuerpo, JsonDocument& resp) {
  if (WiFi.status() != WL_CONNECTED) return -1;
  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(2500);
  if (!http.begin(String(SERVER) + ruta)) return -1;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  int code = http.POST(cuerpo);
  if (code > 0) deserializeJson(resp, http.getString());
  http.end();
  return code;
}

// Lee una tarjeta. Si hay, deja su UID en hexadecimal (ej. "04A1B2C3") y devuelve true.
bool leerTarjetaNFC(String& uidHex) {
  uint8_t uid[7] = {0};
  uint8_t len = 0;
  if (!nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &len, 100) || len == 0) return false;
  uidHex = "";
  for (uint8_t i = 0; i < len; i++) {
    char b[3];
    snprintf(b, sizeof(b), "%02X", uid[i]);
    uidHex += b;
  }
  return true;
}

// Resultado de preguntar a Flask si deja salir
enum Resp { SALE, FALTA_PLACA, DENEGADO, SIN_RED };
Resp pedirSalida(const String& uidHex) {
  JsonDocument doc;
  doc["uid"] = uidHex;
  String cuerpo;
  serializeJson(doc, cuerpo);
  JsonDocument resp;
  int code = postJson("/api/salida/nfc", cuerpo, resp);
  if (code != 200) return SIN_RED;
  if (resp["autorizado"] | false) {
    Serial.printf(">> PAGO/SALIDA OK. Placa %s, cobrado $%d\n", (const char*)(resp["placa"] | "?"), (int)(resp["cobrado"] | 0));
    return SALE;
  }
  String motivo = String(resp["motivo"] | "");
  Serial.printf(">> %s\n", (const char*)(resp["msg"] | motivo.c_str()));
  return motivo == "sin_placa" ? FALTA_PLACA : DENEGADO;
}

// =====================================================================
void setup() {
  Serial.begin(115200);

  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  pinMode(STBY, OUTPUT);
  pinMode(PWMA, OUTPUT);
  pinMode(AIN1, OUTPUT);
  pinMode(AIN2, OUTPUT);
  digitalWrite(STBY, LOW);
  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, LOW);

  nfc.begin();
  uint32_t version = nfc.getFirmwareVersion();
  if (!version) {
    Serial.println("ERROR: No se detectó el PN532. Revisa pines 21 (SDA) y 22 (SCL).");
    while (1) delay(1000);
  }
  nfc.SAMConfig();

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) delay(250);
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[WIFI] Conectado. IP de la ESP32: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("[WIFI] No conectó todavía; seguirá intentando. La barrera no abrirá sin Flask.");
  }

  Serial.println("====================================================");
  Serial.println("ESP32 SALIDA LISTA. Esperando vehículo...");
  Serial.println("====================================================");
}

void loop() {
  unsigned long ahora = millis();
  wifiMantener();

  bool lecturaNueva = false;
  if (ahora - tSensor >= PERIODO_SENSOR) {
    tSensor = ahora;
    dist = medirDistancia();
    lecturaNueva = true;
  }
  bool vehiculo = hayVehiculo(dist);

  switch (estado) {
    case REPOSO:
      if (ahora - tReporte >= 5000) {
        tReporte = ahora;
        Serial.printf("Distancia: %.1f cm | WiFi: %s\n", dist, WiFi.status() == WL_CONNECTED ? "OK" : "SIN CONEXION");
      }
      if (lecturaNueva) presencia = vehiculo ? presencia + 1 : 0;
      if (!vehiculo) {
        if (tLibreReposo == 0) tLibreReposo = ahora;
        else if (ahora - tLibreReposo > 2000) puedeDetectar = true;
      } else {
        tLibreReposo = 0;
      }
      if (presencia >= 3 && puedeDetectar) {
        puedeDetectar = false;
        presencia = 0;
        tAusente = 0;
        tProximaLectura = 0;
        Serial.println(">> VEHÍCULO DETECTADO. Lee la placa en la cámara de salida y acerca la tarjeta NFC...");
        cambiar(ESPERANDO_NFC);
      }
      break;

    case ESPERANDO_NFC: {
      if (!vehiculo) {                       // el carro se fue
        if (tAusente == 0) tAusente = ahora;
        else if (ahora - tAusente > 3000) {
          Serial.println(">> El vehículo se retiró. Cancelado.");
          cambiar(REPOSO);
          break;
        }
      } else {
        tAusente = 0;
      }
      if (ahora - tEstado > VENTANA_NFC_MS) {
        Serial.println(">> Tiempo agotado: no se detectó tarjeta NFC.");
        cambiar(ENFRIAR);
        break;
      }
      if (ahora < tProximaLectura) break;    // pausa tras una respuesta, para no repetir con la tarjeta pegada

      String uid;
      if (leerTarjetaNFC(uid)) {             // aquí el motor está parado: se puede usar la red
        Serial.println("-> Tarjeta NFC detectada. Consultando a Flask...");
        Resp r = pedirSalida(uid);
        if (r == SALE) {
          motorAbrir();
          cambiar(ABRIENDO);
        } else if (r == DENEGADO) {
          cambiar(ENFRIAR);
        } else {
          // FALTA_PLACA o SIN_RED: se puede volver a intentar sin salir de la ventana
          Serial.println(r == FALTA_PLACA ? "   (Aún no hay placa leída: pulsa ESPACIO en la cámara y vuelve a pasar la tarjeta)"
                                          : "   (Flask no respondió: reintenta)");
          tProximaLectura = millis() + 2000;
        }
      }
      break;
    }

    case ABRIENDO:
      if (ahora - tEstado >= T_ABRIR_MS) {
        motorParar(false);   // la pluma se queda arriba
        tDespejado = 0;
        cambiar(ESPERANDO_PASO);
        Serial.println("[MOTOR] Barrera abierta. Esperando a que el vehículo cruce...");
      }
      break;

    case ESPERANDO_PASO:
      if (!vehiculo) {
        if (tDespejado == 0) tDespejado = ahora;
        else if (ahora - tDespejado >= T_DESPEJADO_MS) {
          Serial.println("[MOTOR] Cerrando barrera...");
          motorCerrar();
          cambiar(CERRANDO);
        }
      } else {
        tDespejado = 0;
      }
      break;

    case CERRANDO:   // sin red: solo vigila el sensor
      if (vehiculo) {
        Serial.println(">> ¡OBSTÁCULO DURANTE EL CIERRE! Reabriendo...");
        motorAbrir();
        cambiar(REABRIENDO);
      } else if (ahora - tEstado >= T_CERRAR_MS) {
        motorParar(true);
        Serial.println("[MOTOR] Barrera cerrada. Sistema en reposo.");
        cambiar(ENFRIAR);
      }
      break;

    case REABRIENDO:
      if (ahora - tEstado >= T_REABRIR_MS) {
        motorParar(false);
        tDespejado = 0;
        cambiar(ESPERANDO_PASO);
      }
      break;

    case ENFRIAR:
      if (ahora - tEstado >= 1500) {
        presencia = 0;
        tLibreReposo = 0;
        Serial.println(">> Listo para el siguiente vehículo.\n");
        cambiar(REPOSO);
      }
      break;
  }

  delay(5);
}
