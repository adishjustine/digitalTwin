// Host harness: compiles the real sketch.ino and exercises its pure logic.
// Prints lines that check_firmware.py compares against the Python model.
#include "../sketch.ino"

int main() {
  // 1) Command parser: valid, and several invalid inputs.
  const char* cases[] = {
      "{\"k\":12,\"z\":[[1,1],[0,0],[2,1]]}",   // valid
      "{\"k\":0,\"z\":[[0,0],[0,0],[0,0]]}",    // valid
      "{\"k\":5,\"z\":[[3,1],[0,0],[2,1]]}",    // bad mode
      "{\"k\":5,\"z\":[[1,2],[0,0],[2,1]]}",    // bad light
      "{\"k\":5,\"z\":[[1,1],[0,0]]}",          // too short
      "garbage",
  };
  for (const char* c : cases) {
    int kk = -1, m[NZ] = {9, 9, 9}, l[NZ] = {9, 9, 9};
    bool ok = parseCommand(c, &kk, m, l);
    std::printf("PARSE %d k=%d m=%d%d%d l=%d%d%d\n", ok ? 1 : 0, ok ? kk : -1,
                ok ? m[0] : -1, ok ? m[1] : -1, ok ? m[2] : -1,
                ok ? l[0] : -1, ok ? l[1] : -1, ok ? l[2] : -1);
  }

  // 2) Physics: 300 deterministic steps; print temperatures every 50 steps.
  float Tz[NZ] = {24.0f, 24.0f, 24.0f};
  for (int i = 0; i < 300; i++) {
    float tOutC = 28.0f + 0.01f * i;
    for (int z = 0; z < NZ; z++) {
      int people = (i / 20 + z * 3) % 12;
      int mode = (i / 40 + z) % 3;
      Tz[z] = stepZone(z, Tz[z], tOutC, people, mode, people > 0);
    }
    if (i % 50 == 49) std::printf("TEMP %d %.5f %.5f %.5f\n", i, Tz[0], Tz[1], Tz[2]);
  }
  return 0;
}
