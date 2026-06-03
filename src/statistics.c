#include "statistics.h"
#include <stdio.h>
#include <string.h>

void stats_init(Statistics *s) {
    memset(s, 0, sizeof(Statistics));
    mutex_init(&s->lock);
}

void stats_destroy(Statistics *s) {
    mutex_destroy(&s->lock);
}

void stats_record_park(Statistics *s, int sim_hour, double duration_ms) {
    mutex_lock(&s->lock);
    s->total_parks++;
    if (sim_hour >= 0 && sim_hour < HOURS_PER_DAY) {
        s->park_count_by_hour[sim_hour]++;
    }
    s->total_park_time_ms += duration_ms;
    s->park_ops_timed++;
    mutex_unlock(&s->lock);
}

void stats_record_retrieve(Statistics *s, int sim_hour, double duration_ms) {
    mutex_lock(&s->lock);
    s->total_retrieves++;
    if (sim_hour >= 0 && sim_hour < HOURS_PER_DAY) {
        s->retrieve_count_by_hour[sim_hour]++;
    }
    s->total_retrieve_time_ms += duration_ms;
    s->retrieve_ops_timed++;
    mutex_unlock(&s->lock);
}

void stats_record_movement(Statistics *s, int sim_hour, int step_count) {
    mutex_lock(&s->lock);
    s->total_movements += step_count;
    if (sim_hour >= 0 && sim_hour < HOURS_PER_DAY) {
        s->movement_count_by_hour[sim_hour] += step_count;
    }
    mutex_unlock(&s->lock);
}

void stats_record_fault(Statistics *s, bool retry_succeeded) {
    mutex_lock(&s->lock);
    s->total_faults++;
    if (retry_succeeded) {
        s->total_retries++;
    } else {
        s->total_failed_after_retry++;
    }
    mutex_unlock(&s->lock);
}

void stats_print_summary(const Statistics *s) {
    printf("\n");
    printf("╔══════════════════════════════════════════════╗\n");
    printf("║           仿 真 统 计 报 告                 ║\n");
    printf("╠══════════════════════════════════════════════╣\n");
    printf("║  总存车次数:     %-6d                     ║\n", s->total_parks);
    printf("║  总取车次数:     %-6d                     ║\n", s->total_retrieves);
    printf("║  总移动步骤:     %-6d                     ║\n", s->total_movements);

    if (s->park_ops_timed > 0) {
        printf("║  平均存车耗时:   %-6.0f ms                   ║\n",
               s->total_park_time_ms / s->park_ops_timed);
    }
    if (s->retrieve_ops_timed > 0) {
        printf("║  平均取车耗时:   %-6.0f ms                   ║\n",
               s->total_retrieve_time_ms / s->retrieve_ops_timed);
    }

    printf("║  故障发生次数:   %-6d                     ║\n", s->total_faults);
    printf("║  重试成功次数:   %-6d                     ║\n", s->total_retries);
    printf("║  最终失败次数:   %-6d                     ║\n", s->total_failed_after_retry);
    printf("╠══════════════════════════════════════════════╣\n");

    int peak_hour = 0;
    int peak_ops = 0;
    for (int h = 0; h < HOURS_PER_DAY; h++) {
        int ops = s->park_count_by_hour[h] + s->retrieve_count_by_hour[h];
        if (ops > peak_ops) {
            peak_ops = ops;
            peak_hour = h;
        }
    }

    printf("║  高峰时段: %02d:00-%02d:00 (%d次操作)        ║\n",
           peak_hour, (peak_hour + 1) % 24, peak_ops);
    printf("╠══════════════════════════════════════════════╣\n");
    printf("║  [按小时操作分布]                           ║\n");

    for (int h = 0; h < HOURS_PER_DAY; h++) {
        int ops = s->park_count_by_hour[h] + s->retrieve_count_by_hour[h];
        if (ops == 0) continue;
        printf("║  %02d:00  ", h);
        int bars = ops;
        if (bars > 20) bars = 20;
        for (int b = 0; b < bars; b++) printf("*");
        for (int b = bars; b < 20; b++) printf(" ");
        printf(" (%d)", ops);
        int pad = 5 - (ops >= 10 ? 2 : (ops >= 100 ? 3 : 1));
        for (int p = 0; p < pad; p++) printf(" ");
        printf("  ║\n");
    }

    printf("╚══════════════════════════════════════════════╝\n\n");
}
