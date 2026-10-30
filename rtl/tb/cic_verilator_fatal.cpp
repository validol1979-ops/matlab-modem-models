// Verilator's documented VL_USER_FATAL hook: retain the original diagnostic and
// use the project's exact failure code 13, including failures in axis_check.sv.
#include <cstdio>
#include <cstdlib>
#include "verilated.h"
void vl_fatal(const char* filename, int linenum, const char* hier, const char* msg) {
    std::fprintf(stderr, "%%Error: %s:%d: %s: %s\n", filename, linenum, hier, msg);
    std::fflush(stderr);
    std::exit(13);
}
