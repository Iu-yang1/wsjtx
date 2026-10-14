#include "init_random_seed.h"
#include <errno.h>
#include <limits.h>
#include <stdlib.h>

/* Fortran wrapper. Optional deterministic seed for channel benchmarks.
 * Without WSJT_SIM_SEED retain the upstream time/entropy-based seeding.
 */
void sgran_(void)
{
  const char *setting = getenv("WSJT_SIM_SEED");
  if (setting && *setting) {
    char *end = NULL;
    unsigned long seed;
    errno = 0;
    seed = strtoul(setting, &end, 10);
    if (errno == 0 && end != setting && *end == '\0' && seed <= UINT_MAX) {
      srand((unsigned int)seed);
      return;
    }
  }
  init_random_seed();
}
