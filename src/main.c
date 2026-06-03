#include "cli.h"
#include "simulation.h"
#include <stdio.h>

int main(void) {
    printf("\n");
    printf("╔══════════════════════════════════════════════╗\n");
    printf("║     智能立体车库 停车引导与计费系统 v2.0    ║\n");
    printf("╠══════════════════════════════════════════════╣\n");
    printf("║  [1] 交互式CLI模式  (单线程手动操作)       ║\n");
    printf("║  [2] 多入口仿真模式 (多线程自动仿真)       ║\n");
    printf("╚══════════════════════════════════════════════╝\n");
    printf("\n请选择运行模式 > ");

    int mode;
    if (scanf("%d", &mode) != 1) {
        printf("[错误] 输入无效\n");
        return 1;
    }

    if (mode == 1) {
        ParkingSystem sys;
        cli_init(&sys);
        cli_run(&sys);
    } else if (mode == 2) {
        SimConfig cfg;
        sim_config_default(&cfg);

        printf("\n是否使用默认配置? (Y/n) > ");
        char choice[8];
        scanf("%7s", choice);
        if (choice[0] == 'n' || choice[0] == 'N') {
            printf("仿真时长(秒, 默认30): ");
            scanf("%d", &cfg.simulation_duration_s);
            printf("故障概率(0-100, 默认5): ");
            int prob;
            scanf("%d", &prob);
            cfg.fault_probability = prob / 100.0;
            printf("请求间隔下限(ms, 默认500): ");
            scanf("%d", &cfg.min_request_interval_ms);
            printf("请求间隔上限(ms, 默认2000): ");
            scanf("%d", &cfg.max_request_interval_ms);
        }

        sim_run(&cfg);
    } else {
        printf("[错误] 无效选择\n");
        return 1;
    }

    return 0;
}
