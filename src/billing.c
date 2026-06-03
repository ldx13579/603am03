#include "billing.h"
#include <stdio.h>
#include <string.h>

double billing_calculate(VehicleSize size, time_t entry, time_t exit_time) {
    double diff_seconds = difftime(exit_time, entry);
    int minutes = (int)(diff_seconds / 60.0);
    if (minutes < 0) minutes = 0;

    int billable = minutes - FREE_MINUTES;
    if (billable <= 0) return 0.0;

    double rate = (size == VEHICLE_SMALL) ? RATE_SMALL_PER_MINUTE : RATE_LARGE_PER_MINUTE;
    double fee = billable * rate;

    double cap = (size == VEHICLE_SMALL) ? MAX_DAILY_FEE_SMALL : MAX_DAILY_FEE_LARGE;
    if (fee > cap) fee = cap;

    return fee;
}

void billing_generate_record(const Vehicle *v, BillRecord *record) {
    record->ticket_id = v->id;
    strncpy(record->plate, v->plate, sizeof(record->plate) - 1);
    record->plate[sizeof(record->plate) - 1] = '\0';
    record->size = v->size;
    record->entry_time = v->entry_time;
    record->exit_time = v->exit_time;
    record->duration_minutes = (int)(difftime(v->exit_time, v->entry_time) / 60.0);
    record->fee = billing_calculate(v->size, v->entry_time, v->exit_time);
}

void billing_print_receipt(const BillRecord *record) {
    char entry_buf[32], exit_buf[32];
    struct tm *tm_info;

    tm_info = localtime(&record->entry_time);
    strftime(entry_buf, sizeof(entry_buf), "%Y-%m-%d %H:%M:%S", tm_info);

    tm_info = localtime(&record->exit_time);
    strftime(exit_buf, sizeof(exit_buf), "%Y-%m-%d %H:%M:%S", tm_info);

    printf("\n");
    printf("============== 停车费用单 ==============\n");
    printf("  票号:     %d\n", record->ticket_id);
    printf("  车牌:     %s\n", record->plate);
    printf("  类型:     %s\n", record->size == VEHICLE_SMALL ? "小型车" : "大型车");
    printf("  入场时间: %s\n", entry_buf);
    printf("  出场时间: %s\n", exit_buf);
    printf("  停车时长: %d 分钟\n", record->duration_minutes);
    printf("  费用:     %.2f 元\n", record->fee);
    if (record->duration_minutes <= FREE_MINUTES) {
        printf("  (免费时段: 前%d分钟免费)\n", FREE_MINUTES);
    }
    printf("=========================================\n\n");
}
