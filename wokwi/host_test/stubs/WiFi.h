#pragma once
#include "Arduino.h"
#define WL_CONNECTED 3
struct WiFiClient {};
struct WiFiClass {
  void begin(const char*, const char*, int) {}
  int status() { return WL_CONNECTED; }
};
static WiFiClass WiFi;
