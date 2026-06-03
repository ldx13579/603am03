#ifndef LOGGER_H
#define LOGGER_H

#include "common.h"
#include <stdarg.h>

typedef struct {
    LogEntry entries[MAX_LOG_ENTRIES];
    int      count;
    int      write_index;
} Logger;

void logger_init(Logger *log);
void logger_record(Logger *log, LogType type, int vehicle_id, const char *fmt, ...);
void logger_display(const Logger *log, int last_n);
const char *logger_type_name(LogType type);

#endif
