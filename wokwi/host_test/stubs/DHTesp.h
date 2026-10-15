#pragma once
#include "Arduino.h"
struct TempAndHumidity { float temperature = 30.0f; float humidity = 55.0f; };
struct DHTesp {
  enum DHT_MODEL_t { AUTO_DETECT, DHT11, DHT22 };
  enum DHT_ERROR_t { ERROR_NONE = 0, ERROR_TIMEOUT, ERROR_CHECKSUM };
  void setup(uint8_t, DHT_MODEL_t = AUTO_DETECT) {}
  TempAndHumidity getTempAndHumidity() { return TempAndHumidity(); }
  DHT_ERROR_t getStatus() { return ERROR_NONE; }
};
