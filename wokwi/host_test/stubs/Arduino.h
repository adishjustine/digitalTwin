// Minimal host stand-in for Arduino.h, used only to compile sketch.ino on a PC.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdarg>

typedef uint8_t byte;
#define OUTPUT 1
#define HIGH 1
#define LOW 0

inline uint32_t millis() { static uint32_t t = 0; return t += 7; }
inline uint32_t micros() { static uint32_t t = 0; return t += 1000; }
inline void delay(uint32_t) {}
inline void pinMode(int, int) {}
inline void digitalWrite(int, int) {}
inline int analogRead(int) { return 0; }
inline long map(long x, long a, long b, long c, long d) { return (x - a) * (d - c) / (b - a) + c; }
inline long random(long lo, long hi) { return lo + std::rand() % (hi - lo); }
inline long random(long hi) { return std::rand() % hi; }
inline void randomSeed(unsigned long s) { std::srand((unsigned)s); }

struct SerialStub {
  void begin(int) {}
  void print(const char* s) { std::fputs(s, stdout); }
  void println(const char* s) { std::puts(s); }
  void printf(const char* fmt, ...) {
    va_list a; va_start(a, fmt); std::vfprintf(stdout, fmt, a); va_end(a);
  }
};
static SerialStub Serial;
