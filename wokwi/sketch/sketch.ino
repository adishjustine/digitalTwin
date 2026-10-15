/*
 * DT-BEMS physical layer (ESP32, Wokwi)
 *
 * Simulates the building's physical side:
 *   - DHT22          -> outdoor temperature + humidity
 *   - 3 potentiometers -> occupancy (0-15 people) in Office, Meeting room, Lab
 *   - on-board thermal model (same equations/parameters as models/building.py)
 *     computes each zone's indoor temperature from weather, people, equipment,
 *     lighting and the HVAC mode commanded by the Python digital twin
 *   - 9 LEDs: per zone  [lighting]  [HVAC LOW+HIGH]  [HVAC HIGH]
 *
 * Each tick = 1 simulated minute. Lockstep protocol over MQTT:
 *   1. publish telemetry for tick k          (dtbems/<SITE_ID>/telemetry)
 *   2. wait for the command with the same k  (dtbems/<SITE_ID>/command)
 *   3. apply HVAC/lighting, advance the physics by 1 minute
 *
 * Wire format (see integration/protocol.py):
 *   telemetry {"k":12,"minute":492,"t_out":31.20,"hum":55.0,
 *              "z":[{"T":24.31,"occ":8},{"T":23.90,"occ":0},{"T":25.00,"occ":3}]}
 *   command   {"k":12,"z":[[1,1],[0,0],[2,1]]}   // [hvac 0=OFF 1=LOW 2=HIGH, light]
 *
 * NOTE: the public MQTT broker is visible to everyone. Change SITE_ID to
 * something unique and keep it identical in the Python bridge.
 */
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHTesp.h>

// ------------------------------ Configuration ------------------------------
static const char*    WIFI_SSID   = "Wokwi-GUEST";
static const char*    WIFI_PASS   = "";
static const int      WIFI_CHAN   = 6;
static const char*    MQTT_HOST   = "broker.hivemq.com";
static const uint16_t MQTT_PORT   = 1883;
static const char*    SITE_ID     = "adish-dt-7f3a";   // MUST match the bridge
static const uint32_t TICK_MS     = 1000;   // real ms per simulated minute
static const uint32_t CMD_WAIT_MS = 4000;   // give up waiting for a command
static const int      START_MIN   = 8 * 60; // simulation starts at 08:00

static const int NZ = 3;
static const int PIN_DHT = 15;

struct Zone {
  const char* name;
  int pinPot, pinLight, pinLow, pinHigh;
  float C, UA, equipW, lowW, highW;   // J/degC, W/degC, W, W (electrical), W
};
static const Zone ZONES[NZ] = {
  {"Office",  34, 13, 12, 14, 3.0e6f, 150.0f, 300.0f, 1500.0f, 3000.0f},
  {"Meeting", 35, 27, 26, 25, 1.8e6f, 100.0f, 150.0f, 1000.0f, 2000.0f},
  {"Lab",     32, 23, 22, 21, 4.0e6f, 180.0f, 800.0f, 1500.0f, 3000.0f},
};
static const float LIGHT_W = 400.0f;    // lighting power = heat when ON
static const float COP = 2.0f;          // cooling delivered per electrical watt
static const float OCC_HEAT_W = 100.0f; // heat per person
static const float DT_S = 60.0f;        // one simulated minute

// ---------------------------------- State ----------------------------------
static WiFiClient wifi;
static PubSubClient mqtt(wifi);
static DHTesp dht;

static char TOPIC_TELE[64];
static char TOPIC_CMD[64];

static float T[NZ];                 // true indoor temperatures
static int   occ[NZ];
static int   modeCmd[NZ]  = {0, 0, 0};
static int   lightCmd[NZ] = {0, 0, 0};
static float tOut = 30.0f, hum = 55.0f;
static int   k = 0;

static volatile int  rxK = -1;      // k of the last valid command received
static int           rxMode[NZ];
static int           rxLight[NZ];

// ------------------------------- Pure logic --------------------------------
// One explicit step of the RC thermal model (identical to step_temp() in Python).
static float stepZone(int i, float Tz, float tOutC, int people, int mode, bool light) {
  const Zone& z = ZONES[i];
  float qEnv   = z.UA * (tOutC - Tz);
  float qOcc   = people * OCC_HEAT_W;
  float qEquip = z.equipW + (light ? LIGHT_W : 0.0f);
  float elec   = (mode == 0) ? 0.0f : (mode == 1 ? z.lowW : z.highW);
  float qHvac  = elec * COP;
  return Tz + DT_S / z.C * (qEnv + qOcc + qEquip - qHvac);
}

// Parses {"k":12,"z":[[1,1],[0,0],[2,1]]}. Returns true only for a valid message.
static bool parseCommand(const char* s, int* kOut, int mode[NZ], int light[NZ]) {
  int n = sscanf(s, "{\"k\":%d,\"z\":[[%d,%d],[%d,%d],[%d,%d]]}", kOut,
                 &mode[0], &light[0], &mode[1], &light[1], &mode[2], &light[2]);
  if (n != 7) return false;
  for (int i = 0; i < NZ; i++) {
    if (mode[i] < 0 || mode[i] > 2 || light[i] < 0 || light[i] > 1) return false;
  }
  return true;
}

static const char* modeName(int m) { return m == 0 ? "OFF" : (m == 1 ? "LOW" : "HIGH"); }

// --------------------------------- Hardware --------------------------------
static void writeOutputs() {
  for (int i = 0; i < NZ; i++) {
    digitalWrite(ZONES[i].pinLight, lightCmd[i] ? HIGH : LOW);
    digitalWrite(ZONES[i].pinLow,   modeCmd[i] >= 1 ? HIGH : LOW);
    digitalWrite(ZONES[i].pinHigh,  modeCmd[i] == 2 ? HIGH : LOW);
  }
}

static void readSensors() {
  TempAndHumidity th = dht.getTempAndHumidity();
  if (dht.getStatus() == DHTesp::ERROR_NONE) {
    tOut = th.temperature;
    hum = th.humidity;
  }
  for (int i = 0; i < NZ; i++) {
    occ[i] = map(analogRead(ZONES[i].pinPot), 0, 4095, 0, 15);
  }
}

// -------------------------------- Networking -------------------------------
static void onMessage(char* topic, byte* payload, unsigned int len) {
  (void)topic;
  char buf[96];
  if (len == 0 || len >= sizeof(buf)) return;
  memcpy(buf, payload, len);
  buf[len] = 0;
  int kk, m[NZ], l[NZ];
  if (!parseCommand(buf, &kk, m, l)) {
    Serial.printf("Ignoring malformed command: %s\n", buf);
    return;
  }
  for (int i = 0; i < NZ; i++) { rxMode[i] = m[i]; rxLight[i] = l[i]; }
  rxK = kk;   // set last: the loop watches this
}

static void connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("WiFi connecting");
  WiFi.begin(WIFI_SSID, WIFI_PASS, WIFI_CHAN);
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  Serial.println(" connected");
}

static void connectMqtt() {
  while (!mqtt.connected()) {
    char cid[32];
    snprintf(cid, sizeof(cid), "dtbems-esp32-%04x", (unsigned)random(0xFFFF));
    Serial.printf("MQTT connecting to %s ...\n", MQTT_HOST);
    if (mqtt.connect(cid)) {
      mqtt.subscribe(TOPIC_CMD);
      Serial.printf("MQTT connected, listening on %s\n", TOPIC_CMD);
    } else {
      Serial.printf("MQTT failed (rc=%d), retrying\n", mqtt.state());
      delay(1500);
    }
  }
}

static bool waitForCommand(int expectK, uint32_t timeoutMs) {
  uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    mqtt.loop();
    if (rxK == expectK) return true;
    delay(5);
  }
  return false;
}

static void publishTelemetry(const float obs[NZ]) {
  char buf[320];
  snprintf(buf, sizeof(buf),
           "{\"k\":%d,\"minute\":%d,\"t_out\":%.2f,\"hum\":%.1f,"
           "\"z\":[{\"T\":%.2f,\"occ\":%d},{\"T\":%.2f,\"occ\":%d},{\"T\":%.2f,\"occ\":%d}]}",
           k, (START_MIN + k) % 1440, tOut, hum,
           obs[0], occ[0], obs[1], occ[1], obs[2], occ[2]);
  mqtt.publish(TOPIC_TELE, buf);
}

// ------------------------------- Arduino entry -----------------------------
void setup() {
  Serial.begin(115200);
  randomSeed(micros());
  for (int i = 0; i < NZ; i++) {
    pinMode(ZONES[i].pinLight, OUTPUT);
    pinMode(ZONES[i].pinLow, OUTPUT);
    pinMode(ZONES[i].pinHigh, OUTPUT);
    T[i] = 24.0f;
  }
  writeOutputs();
  dht.setup(PIN_DHT, DHTesp::DHT22);

  snprintf(TOPIC_TELE, sizeof(TOPIC_TELE), "dtbems/%s/telemetry", SITE_ID);
  snprintf(TOPIC_CMD,  sizeof(TOPIC_CMD),  "dtbems/%s/command",   SITE_ID);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setCallback(onMessage);

  Serial.println("DT-BEMS physical layer starting (1 tick = 1 simulated minute)");
  connectWifi();
  connectMqtt();
}

void loop() {
  uint32_t tickStart = millis();
  connectWifi();
  connectMqtt();

  readSensors();

  // Sensor readings carry a little noise, like the offline simulator.
  float obs[NZ];
  for (int i = 0; i < NZ; i++) obs[i] = T[i] + random(-200, 201) / 1000.0f;

  publishTelemetry(obs);
  if (waitForCommand(k, CMD_WAIT_MS)) {
    for (int i = 0; i < NZ; i++) { modeCmd[i] = rxMode[i]; lightCmd[i] = rxLight[i]; }
  } else {
    Serial.printf("k=%d: no command from the Python app, keeping previous settings\n", k);
  }
  writeOutputs();

  // Advance the physics one minute using the commanded HVAC/lighting.
  for (int i = 0; i < NZ; i++) {
    T[i] = stepZone(i, T[i], tOut, occ[i], modeCmd[i], lightCmd[i] != 0);
  }

  int minute = (START_MIN + k) % 1440;
  Serial.printf("[%02d:%02d] k=%d out=%.1fC hum=%.0f%% | ", minute / 60, minute % 60, k, tOut, hum);
  for (int i = 0; i < NZ; i++) {
    Serial.printf("%s %.1fC occ=%d %s%s%s", ZONES[i].name, T[i], occ[i], modeName(modeCmd[i]),
                  lightCmd[i] ? "+L" : "", i < NZ - 1 ? " | " : "\n");
  }
  k++;

  while (millis() - tickStart < TICK_MS) {   // pace the simulation
    mqtt.loop();
    delay(5);
  }
}
