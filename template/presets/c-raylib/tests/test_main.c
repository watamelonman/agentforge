#include "core/check.h"

#include <stdio.h>

/* Each test file adds its suite here; keep this list sorted. */
static void test_harness_counts(void) { CHECK(g_check_failures == 0); }

int main(void) {
    test_harness_counts();
    printf("%s (%d failures)\n", g_check_failures ? "FAIL" : "OK", g_check_failures);
    return g_check_failures ? 1 : 0;
}
