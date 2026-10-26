#include "core/check.h"

#include <stdio.h>

int g_check_failures = 0;

void check_fail(const char *expr, const char *file, int line) {
    fprintf(stderr, "%s:%d: CHECK failed: %s\n", file, line, expr);
    g_check_failures++;
}
