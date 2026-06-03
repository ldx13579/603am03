#include "state_machine.h"
#include <stdio.h>

void sm_init(StateMachine *sm) {
    sm->current_state = STATE_IDLE;
    sm->active_vehicle_id = -1;
}

ErrorCode sm_handle_event(StateMachine *sm, Event event, int vehicle_id) {
    switch (sm->current_state) {
    case STATE_IDLE:
        if (event == EVENT_PARK_REQUEST) {
            sm->current_state = STATE_PARKING;
            sm->active_vehicle_id = vehicle_id;
            return ERR_OK;
        }
        if (event == EVENT_RETRIEVE_REQUEST) {
            sm->current_state = STATE_RETRIEVING;
            sm->active_vehicle_id = vehicle_id;
            return ERR_OK;
        }
        break;

    case STATE_PARKING:
        if (event == EVENT_MOVE_COMPLETE) {
            sm->current_state = STATE_IDLE;
            sm->active_vehicle_id = -1;
            return ERR_OK;
        }
        if (event == EVENT_ERROR_OCCURRED) {
            sm->current_state = STATE_ERROR;
            return ERR_OK;
        }
        break;

    case STATE_RETRIEVING:
        if (event == EVENT_MOVE_COMPLETE) {
            sm->current_state = STATE_IDLE;
            sm->active_vehicle_id = -1;
            return ERR_OK;
        }
        if (event == EVENT_ERROR_OCCURRED) {
            sm->current_state = STATE_ERROR;
            return ERR_OK;
        }
        break;

    case STATE_ERROR:
        if (event == EVENT_RESET) {
            sm->current_state = STATE_IDLE;
            sm->active_vehicle_id = -1;
            return ERR_OK;
        }
        break;
    }

    return ERR_STATE_CONFLICT;
}

SystemState sm_get_state(const StateMachine *sm) {
    return sm->current_state;
}

const char *sm_state_name(SystemState state) {
    switch (state) {
    case STATE_IDLE:       return "空闲";
    case STATE_PARKING:    return "存车中";
    case STATE_RETRIEVING: return "取车中";
    case STATE_ERROR:      return "故障";
    default:               return "未知";
    }
}
