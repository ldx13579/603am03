#include "logger.h"
#include <stdio.h>
#include <string.h>
#include <stdarg.h>

void logger_init(Logger *log) {
    memset(log, 0, sizeof(Logger));
}

const char *logger_type_name(LogType type) {
    switch (type) {
    case LOG_PARK:     return "存车";
    case LOG_RETRIEVE: return "取车";
    case LOG_MOVE:     return "移动";
    case LOG_BLOCKAGE: return "阻塞";
    case LOG_BILLING:  return "计费";
    case LOG_ERROR:    return "错误";
    default:           return "未知";
    }
}

void logger_record(Logger *log, LogType type, int vehicle_id, const char *fmt, ...) {
    LogEntry *entry = &log->entries[log->write_index];
    entry->type = type;
    entry->timestamp = time(NULL);
    entry->vehicle_id = vehicle_id;

    va_list args;
    va_start(args, fmt);
    vsnprintf(entry->message, sizeof(entry->message), fmt, args);
    va_end(args);

    log->write_index = (log->write_index + 1) % MAX_LOG_ENTRIES;
    if (log->count < MAX_LOG_ENTRIES) {
        log->count++;
    }
}

void logger_display(const Logger *log, int last_n) {
    if (log->count == 0) {
        printf("  (暂无操作记录)\n");
        return;
    }

    int start;
    int display_count = (last_n > 0 && last_n < log->count) ? last_n : log->count;

    if (log->count < MAX_LOG_ENTRIES) {
        start = log->count - display_count;
    } else {
        start = (log->write_index - display_count + MAX_LOG_ENTRIES) % MAX_LOG_ENTRIES;
    }

    printf("\n============== 操作日志 (最近%d条) ==============\n", display_count);
    for (int i = 0; i < display_count; i++) {
        int idx = (start + i) % MAX_LOG_ENTRIES;
        const LogEntry *e = &log->entries[idx];

        char time_buf[32];
        struct tm *tm_info = localtime(&e->timestamp);
        strftime(time_buf, sizeof(time_buf), "%H:%M:%S", tm_info);

        printf("  [%s][%s] 票号:%d %s\n",
               time_buf, logger_type_name(e->type), e->vehicle_id, e->message);
    }
    printf("==================================================\n\n");
}
