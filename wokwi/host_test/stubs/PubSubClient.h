#pragma once
#include "Arduino.h"
#include "WiFi.h"
struct PubSubClient {
  explicit PubSubClient(WiFiClient&) {}
  PubSubClient& setServer(const char*, uint16_t) { return *this; }
  PubSubClient& setCallback(void (*)(char*, byte*, unsigned int)) { return *this; }
  bool setBufferSize(uint16_t) { return true; }
  bool connected() { return true; }
  bool connect(const char*) { return true; }
  bool subscribe(const char*) { return true; }
  bool publish(const char*, const char*) { return true; }
  bool loop() { return true; }
  int state() { return 0; }
};
