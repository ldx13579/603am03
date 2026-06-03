#ifndef CLI_H
#define CLI_H

#include "common.h"
#include "garage.h"
#include "state_machine.h"
#include "path_planner.h"
#include "billing.h"
#include "logger.h"

typedef struct {
    Garage       garage;
    StateMachine sm;
    Logger       logger;
} ParkingSystem;

void cli_init(ParkingSystem *sys);
void cli_run(ParkingSystem *sys);
void cli_show_menu(const ParkingSystem *sys);
void cli_handle_park(ParkingSystem *sys);
void cli_handle_retrieve(ParkingSystem *sys);
void cli_print_sequence(const MovementSequence *seq);

#endif
