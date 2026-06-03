#include "cli.h"
#include <stdio.h>

int main(void) {
    ParkingSystem sys;
    cli_init(&sys);
    cli_run(&sys);
    return 0;
}
