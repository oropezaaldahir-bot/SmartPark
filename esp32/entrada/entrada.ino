// ====================================================================
// SMARTPARK · ESP32 #1 · MÓDULO DE ENTRADA (WiFi + Flask)
//
// Qué hace:
//   - Mide los 4 cajones y los muestra en la pantalla TFT (como antes).
//   - Cada 5 s manda el estado de los cajones a Flask:  POST /api/entrada/estado
//   - Cuando llega un carro al sensor de la pluma, pregunta a Flask si abre:
//       POST /api/entrada/vehiculo   (Flask usa la placa que leyó la cámara de entrada)
//     y si Flask dice que sí, abre, espera a que el carro pase y cierra.
//   - La seguridad antiatropello es LOCAL: no depende de la red.
//   - Mientras la barrera se mueve NO se hace ninguna llamada de red.
//
// Librerías (Administrador de bibliotecas de Arduino IDE):
//   ArduinoJson 7.x, Adafruit GFX, Adafruit ST7735 and ST7789  (WiFi y HTTPClient ya vienen con el ESP32)
//
// En Flask:  python app.py   (escucha en 0.0.0.0:5000) y la PC con IP fija o reservada.
// ====================================================================
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>

// ===================== AJUSTA ESTO =====================
const char* WIFI_SSID = "TU_WIFI";
const char* WIFI_PASS = "TU_CLAVE";
const char* SERVER    = "http://192.168.1.50:5000";  // IP de tu PC (donde corre app.py)
const char* API_KEY   = "smartpark-esp32";           // igual que ESP32_TOKEN en Flask (config.py)
// =======================================================

// 1. PINES PANTALLA TFT ST7789 (SPI)
#define TFT_CS   5
#define TFT_DC   2
#define TFT_RST  4
Adafruit_ST7789 tft = Adafruit_ST7789(TFT_CS, TFT_DC, TFT_RST);

// 2. SENSORES DE CAJONES (HC-SR04)
const int trigCajones[4] = {32, 33, 26, 27};
const int echoCajones[4] = {34, 35, 36, 39};  // con divisores de voltaje

// 3. SENSOR DE LA PLUMA / ANTIATROPELLO
const int trigSeguridad = 22;
const int echoSeguridad = 21;  // con divisor de voltaje

// 4. DRIVER TB6612FNG (BARRERA DE ENTRADA)
const int STBY = 13;
const int PWMA = 25;
const int AIN1 = 16;
const int AIN2 = 17;

// ---------- umbrales y tiempos ----------
const float UMBRAL_CAJON     = 12.0;   // cm: menos que esto = cajón ocupado
const float UMBRAL_SEGURIDAD = 10.0;   // cm: menos que esto = hay algo en la pluma
const int   VELOCIDAD        = 220;    // PWM 0-255
const unsigned long T_ABRIR_MS       = 2000;   // ajusta al recorrido de tu pluma
const unsigned long T_CERRAR_MS      = 2000;
const unsigned long T_REABRIR_MS     = 1500;
const unsigned long T_DESPEJADO_MS   = 1500;   // el sensor debe verse libre este tiempo antes de cerrar
const unsigned long VENTANA_PLACA_MS = 30000;  // cuánto espera la lectura de la placa
const unsigned long PERIODO_REPORTE  = 5000;   // estado a Flask y reporte por Serial
const unsigned long PERIODO_CAJONES  = 300;
const unsigned long PERIODO_SEGURIDAD = 50;
const unsigned long PERIODO_PREGUNTA = 1000;   // cada cuánto pregunta a Flask si ya hay placa
const unsigned long T_ULTRA_US = 6000;         // timeout del eco (~100 cm): evita bloqueos largos

// ---------- estado de los cajones ----------
bool  ocupado[4]       = {false, false, false, false};
int8_t cajonPantalla[4] = {-1, -1, -1, -1};     // -1 = aún no dibujado
float distCajon[4]     = {999, 999, 999, 999};
int   libres           = 4;
int   librePantalla    = -1;

// ---------- máquina de estados de la barrera ----------
enum Estado { REPOSO, ESPERANDO_PLACA, ABRIENDO, ESPERANDO_PASO, CERRANDO, REABRIENDO, ENFRIAR };
Estado estado = REPOSO;
unsigned long tEstado = 0;       // cuándo se entró al estado actual
unsigned long tEnfriar = 2000;   // duración del estado ENFRIAR

float dSeg = 999;                // última distancia del sensor de la pluma
int   presencia = 0;             // lecturas seguidas con objeto (antirrebote)
bool  puedeDetectar = true;      // se rearma cuando el sensor se queda libre un rato
unsigned long tLibreReposo = 0;  // desde cuándo el sensor está libre en REPOSO
unsigned long tDespejado = 0;    // desde cuándo está libre en ESPERANDO_PASO
unsigned long tUltimaPregunta = 0;
unsigned long tAusente = 0;
String cajonAsignado = "";

unsigned long tCajones = 0, tSeguridad = 0, tReporte = 0, tWifi = 0;

// =====================================================================
//  Sensores
// =====================================================================
float medirDistancia(int tPin, int ePin) {
  digitalWrite(tPin, LOW);
  delayMicroseconds(2);
  digitalWrite(tPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(tPin, LOW);
  long dur = pulseIn(ePin, HIGH, T_ULTRA_US);
  if (dur == 0) return 999.0;
  return dur * 0.034 / 2.0;
}

bool hayObjeto(float d) { return d > 0.5 && d < UMBRAL_SEGURIDAD; }

void leerCajones() {
  libres = 0;
  for (int i = 0; i < 4; i++) {
    distCajon[i] = medirDistancia(trigCajones[i], echoCajones[i]);
    ocupado[i] = (distCajon[i] > 0.5 && distCajon[i] < UMBRAL_CAJON);
    if (!ocupado[i]) libres++;
    delay(25);  // evita que un sensor oiga el eco del anterior
  }
}

// =====================================================================
//  Motor
// =====================================================================
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
void cambiar(Estado e) { estado = e; tEstado = millis(); }

// =====================================================================
//  Pantalla
// =====================================================================
void pantallaMensaje(const char* texto, uint16_t color) {
  tft.fillRect(0, 42, 240, 48, ST77XX_BLACK);
  tft.setCursor(12, 52);
  tft.setTextSize(2);
  tft.setTextColor(color);
  tft.print(texto);
}

void actualizarPantalla() {
  if (libres != librePantalla) {
    if (libres > 0) {
      char buf[24];
      snprintf(buf, sizeof(buf), "LIBRES: %d / 4", libres);
      pantallaMensaje(buf, ST77XX_GREEN);
    } else {
      pantallaMensaje("ESTAC. LLENO", ST77XX_RED);
    }
    librePantalla = libres;
  }
  for (int i = 0; i < 4; i++) {
    if ((int8_t)ocupado[i] != cajonPantalla[i]) {
      int x = (i % 2 == 0) ? 10 : 125;
      int y = (i < 2) ? 98 : 168;
      tft.fillRoundRect(x, y, 105, 60, 8, ocupado[i] ? ST77XX_RED : ST77XX_GREEN);
      tft.setTextColor(ST77XX_BLACK);
      tft.setTextSize(2);
      tft.setCursor(x + 12, y + 10);
      tft.print("CAJON ");
      tft.print(i + 1);
      tft.setCursor(x + 12, y + 34);
      tft.print(ocupado[i] ? "OCUPADO" : "LIBRE");
      cajonPantalla[i] = ocupado[i];
    }
  }
}

// =====================================================================
//  Red
// =====================================================================
void wifiMantener() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - tWifi < 10000) return;
  tWifi = millis();
  Serial.println("[WIFI] Sin conexión, reintentando...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
}

// POST JSON a Flask. Devuelve el código HTTP (200 = bien) o -1 si no hubo red.
int postJson(const char* ruta, const String& cuerpo, JsonDocument& resp) {
  if (WiFi.status() != WL_CONNECTED) return -1;
  HTTPClient http;
  http.setConnectTimeout(1500);
  http.setTimeout(2000);
  if (!http.begin(String(SERVER) + ruta)) return -1;
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  int code = http.POST(cuerpo);
  if (code > 0) deserializeJson(resp, http.getString());
  http.end();
  return code;
}

void reportarEstado() {
  JsonDocument doc;
  JsonArray arr = doc["cajones"].to<JsonArray>();
  for (int i = 0; i < 4; i++) arr.add(ocupado[i]);
  String cuerpo;
  serializeJson(doc, cuerpo);
  JsonDocument resp;
  int code = postJson("/api/entrada/estado", cuerpo, resp);
  Serial.printf("[API] estado -> HTTP %d\n", code);
}

// 1 = abrir, 0 = todavía no hay placa, -1 = denegado (motivo en 'msgDenegado'), -2 = error de red
String msgDenegado = "";
int preguntarEntrada() {
  JsonDocument resp;
  int code = postJson("/api/entrada/vehiculo", "{}", resp);
  if (code != 200) return -2;
  if (resp["abrir"] | false) {
    cajonAsignado = String(resp["cajon"] | "?");
    Serial.printf("[API] ABRIR. Placa %s, cajón %s\n", (const char*)(resp["placa"] | "?"), cajonAsignado.c_str());
    return 1;
  }
  String motivo = String(resp["motivo"] | "");
  if (motivo == "esperando_placa") return 0;
  if (motivo == "inside")       msgDenegado = "YA ESTA DENTRO";
  else if (motivo == "full")    msgDenegado = "ESTAC. LLENO";
  else if (motivo == "unknown") msgDenegado = "PLACA NO REGISTRADA";
  else if (motivo == "early")   msgDenegado = "RESERVA: MUY PRONTO";
  else                          msgDenegado = "ACCESO DENEGADO";
  Serial.printf("[API] DENEGADO (%s)\n", motivo.c_str());
  return -1;
}

// =====================================================================
void setup() {
  Serial.begin(115200);

  for (int i = 0; i < 4; i++) {
    pinMode(trigCajones[i], OUTPUT);
    pinMode(echoCajones[i], INPUT);
    digitalWrite(trigCajones[i], LOW);
  }
  pinMode(trigSeguridad, OUTPUT);
  pinMode(echoSeguridad, INPUT);
  digitalWrite(trigSeguridad, LOW);

  pinMode(STBY, OUTPUT);
  pinMode(PWMA, OUTPUT);
  pinMode(AIN1, OUTPUT);
  pinMode(AIN2, OUTPUT);
  digitalWrite(STBY, LOW);
  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, LOW);

  tft.init(240, 240, SPI_MODE3);
  tft.setRotation(2);
  tft.fillScreen(ST77XX_BLACK);
  tft.fillRect(0, 0, 240, 38, ST77XX_BLUE);
  tft.setTextColor(ST77XX_WHITE);
  tft.setTextSize(2);
  tft.setCursor(18, 11);
  tft.println("SMARTPARK ENTRADA");

  pantallaMensaje("CONECTANDO WIFI", ST77XX_YELLOW);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) delay(250);
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[WIFI] Conectado. IP de la ESP32: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("[WIFI] No conectó todavía; seguirá intentando. La barrera no abrirá sola sin Flask.");
  }

  Serial.println("====================================================");
  Serial.println("ESP32 ENTRADA LISTA. ('A' por Serial = abrir sin Flask, para pruebas)");
  Serial.println("====================================================");
}

void loop() {
  unsigned long ahora = millis();
  wifiMantener();

  // Sensor de la pluma: se lee en TODOS los estados
  bool lecturaNueva = false;
  if (ahora - tSeguridad >= PERIODO_SEGURIDAD) {
    tSeguridad = ahora;
    dSeg = medirDistancia(trigSeguridad, echoSeguridad);
    lecturaNueva = true;
  }
  bool objeto = hayObjeto(dSeg);

  // Prueba por Serial: 'A' abre sin preguntar a Flask
  if (Serial.available() > 0) {
    char c = Serial.read();
    if ((c == 'A' || c == 'a') && estado == REPOSO) {
      Serial.println("[PRUEBA] Abriendo sin Flask...");
      cajonAsignado = "--";
      motorAbrir();
      cambiar(ABRIENDO);
    }
  }

  switch (estado) {
    case REPOSO: {
      if (ahora - tCajones >= PERIODO_CAJONES) {
        tCajones = ahora;
        leerCajones();
        actualizarPantalla();
      }

      if (ahora - tReporte >= PERIODO_REPORTE) {
        tReporte = ahora;
        Serial.println("----------------------------------------");
        Serial.printf("  Pluma: %.1f cm | WiFi: %s\n", dSeg, WiFi.status() == WL_CONNECTED ? "OK" : "SIN CONEXION");
        for (int i = 0; i < 4; i++) Serial.printf("  Cajon %d: %.1f cm %s\n", i + 1, distCajon[i], ocupado[i] ? "(ocupado)" : "");
        reportarEstado();
      }

      // Antirrebote: 3 lecturas NUEVAS seguidas con objeto = llegó un carro
      if (lecturaNueva) presencia = objeto ? presencia + 1 : 0;
      if (!objeto) {
        if (tLibreReposo == 0) tLibreReposo = ahora;
        else if (ahora - tLibreReposo > 2000) puedeDetectar = true;
      } else {
        tLibreReposo = 0;
      }

      if (presencia >= 3 && puedeDetectar) {
        puedeDetectar = false;  // no vuelve a disparar hasta que el sensor quede libre
        presencia = 0;
        if (libres == 0) {
          Serial.println(">> ACCESO DENEGADO: estacionamiento lleno.");
          pantallaMensaje("ESTAC. LLENO", ST77XX_RED);
          tEnfriar = 3000;
          cambiar(ENFRIAR);
        } else {
          Serial.println(">> Vehículo en la entrada. Esperando la placa de la cámara...");
          pantallaMensaje("LEYENDO PLACA...", ST77XX_YELLOW);
          tUltimaPregunta = 0;
          tAusente = 0;
          cambiar(ESPERANDO_PLACA);
        }
      }
      break;
    }

    case ESPERANDO_PLACA: {
      // si el carro se fue, cancela
      if (!objeto) {
        if (tAusente == 0) tAusente = ahora;
        else if (ahora - tAusente > 3000) {
          Serial.println(">> El vehículo se retiró. Cancelado.");
          librePantalla = -1;
          cambiar(REPOSO);
          break;
        }
      } else {
        tAusente = 0;
      }

      if (ahora - tEstado > VENTANA_PLACA_MS) {
        Serial.println(">> Sin lectura de placa a tiempo.");
        pantallaMensaje("SIN LECTURA PLACA", ST77XX_RED);
        tEnfriar = 3000;
        cambiar(ENFRIAR);
        break;
      }

      if (ahora - tUltimaPregunta >= PERIODO_PREGUNTA) {   // aquí el motor está parado: se puede usar la red
        tUltimaPregunta = ahora;
        int r = preguntarEntrada();
        if (r == 1) {
          char buf[28];
          snprintf(buf, sizeof(buf), "CAJON ASIGNADO: %s", cajonAsignado.c_str());
          pantallaMensaje(buf, ST77XX_GREEN);
          motorAbrir();
          cambiar(ABRIENDO);
        } else if (r == -1) {
          pantallaMensaje(msgDenegado.c_str(), ST77XX_RED);
          tEnfriar = 3000;
          cambiar(ENFRIAR);
        } else if (r == -2) {
          Serial.println("[API] Sin respuesta de Flask, reintentando...");
        }
      }
      break;
    }

    case ABRIENDO:
      if (ahora - tEstado >= T_ABRIR_MS) {
        motorParar(false);   // la pluma se queda arriba
        tDespejado = 0;
        cambiar(ESPERANDO_PASO);
        Serial.println("[MOTOR] Barrera abierta. Esperando a que el vehículo pase...");
      }
      break;

    case ESPERANDO_PASO:
      if (!objeto) {
        if (tDespejado == 0) tDespejado = ahora;
        else if (ahora - tDespejado >= T_DESPEJADO_MS) {
          Serial.println("[MOTOR] Zona libre. Cerrando barrera...");
          motorCerrar();
          cambiar(CERRANDO);
        }
      } else {
        tDespejado = 0;
      }
      break;

    case CERRANDO:   // sin llamadas de red ni lecturas largas: solo el sensor de la pluma
      if (objeto) {
        Serial.println(">> ¡OBSTÁCULO DURANTE EL CIERRE! Reabriendo...");
        motorAbrir();
        cambiar(REABRIENDO);
      } else if (ahora - tEstado >= T_CERRAR_MS) {
        motorParar(true);
        Serial.println("[MOTOR] Barrera cerrada y asegurada.");
        tEnfriar = 2000;
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
      if (ahora - tEstado >= tEnfriar) {
        librePantalla = -1;   // vuelve a dibujar el contador de libres
        presencia = 0;
        tLibreReposo = 0;
        cambiar(REPOSO);
      }
      break;
  }

  delay(5);
}
