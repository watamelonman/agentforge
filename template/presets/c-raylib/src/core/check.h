#ifndef CORE_CHECK_H
#define CORE_CHECK_H

/* Minimal test harness so tests need no third-party dependency. */
extern int g_check_failures;

/* Records a failure with file:line instead of aborting, so one run reports every failure. */
void check_fail(const char *expr, const char *file, int line);

#define CHECK(expr) ((expr) ? (void)0 : check_fail(#expr, __FILE__, __LINE__))

#endif
