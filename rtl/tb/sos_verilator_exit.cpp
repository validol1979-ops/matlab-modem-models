// --binary keeps Verilator's generated timing main. Use the supported fatal hook
// (compiled with VL_USER_FATAL) to return the project's exact failure code.
// The runner additionally requires the original, precise scoreboard/checker tag.
#include "verilated.h"
#include <cstdio>
#include <cstdlib>
void vl_fatal(const char* filename, int linenum, const char*, const char* message) {
    std::fprintf(stderr, "%%Error: %s:%d: %s\n", filename, linenum, message);
    Verilated::runFlushCallbacks();
    std::fflush(nullptr);
    std::exit(13);
}
