#include "cli.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

void cli_init(ParkingSystem *sys) {
    garage_init(&sys->garage);
    sm_init(&sys->sm);
    logger_init(&sys->logger);
}

void cli_show_menu(const ParkingSystem *sys) {
    printf("\n");
    printf("╔══════════════════════════════════════════════╗\n");
    printf("║     智能立体车库 停车引导与计费系统         ║\n");
    printf("╠══════════════════════════════════════════════╣\n");
    printf("║  [1] 存车  - 停入车辆                      ║\n");
    printf("║  [2] 取车  - 取出车辆                      ║\n");
    printf("║  [3] 状态  - 显示车库布局                  ║\n");
    printf("║  [4] 日志  - 查看操作记录                  ║\n");
    printf("║  [0] 退出  - 关闭系统                      ║\n");
    printf("╚══════════════════════════════════════════════╝\n");
    printf("  系统状态: %s\n", sm_state_name(sm_get_state(&sys->sm)));
    printf("  空闲车位: 小型%d 大型%d\n",
           garage_count_free(&sys->garage, VEHICLE_SMALL),
           garage_count_free(&sys->garage, VEHICLE_LARGE));
    printf("\n请输入指令 > ");
}

void cli_print_sequence(const MovementSequence *seq) {
    printf("\n--- 动作序列 ---\n");
    for (int i = 0; i < seq->count; i++) {
        printf("  步骤 %d: %s\n", i + 1, seq->steps[i].description);
    }
    printf("--- 序列结束 ---\n\n");
}

void cli_handle_park(ParkingSystem *sys) {
    if (sm_get_state(&sys->sm) != STATE_IDLE) {
        printf("[错误] 系统忙，请稍后再试。当前状态: %s\n", sm_state_name(sm_get_state(&sys->sm)));
        return;
    }

    char plate[16];
    char size_input[8];
    VehicleSize size;

    printf("请输入车牌号: ");
    if (scanf("%15s", plate) != 1) {
        printf("[错误] 输入无效\n");
        while (getchar() != '\n');
        return;
    }

    printf("请输入车辆类型 (S=小型, L=大型): ");
    if (scanf("%7s", size_input) != 1) {
        printf("[错误] 输入无效\n");
        while (getchar() != '\n');
        return;
    }

    if (size_input[0] == 'S' || size_input[0] == 's') {
        size = VEHICLE_SMALL;
    } else if (size_input[0] == 'L' || size_input[0] == 'l') {
        size = VEHICLE_LARGE;
    } else {
        printf("[错误] 无效的车辆类型，请输入 S 或 L\n");
        return;
    }

    SpotLocation spot;
    ErrorCode err = planner_assign_spot(&sys->garage, size, &spot);
    if (err != ERR_OK) {
        printf("[错误] 车库已满或无适配车位！\n");
        logger_record(&sys->logger, LOG_ERROR, 0, "存车失败: 车牌%s, 无可用车位", plate);
        return;
    }

    sm_handle_event(&sys->sm, EVENT_PARK_REQUEST, 0);

    MovementSequence seq;
    err = planner_plan_park(&sys->garage, spot, &seq);
    if (err != ERR_OK) {
        printf("[错误] 路径规划失败！\n");
        sm_handle_event(&sys->sm, EVENT_ERROR_OCCURRED, 0);
        logger_record(&sys->logger, LOG_ERROR, 0, "路径规划失败: 车牌%s", plate);
        return;
    }

    int ticket = garage_add_vehicle(&sys->garage, plate, size, spot.level, spot.position);
    if (ticket < 0) {
        printf("[错误] 车辆入库失败！\n");
        sm_handle_event(&sys->sm, EVENT_ERROR_OCCURRED, 0);
        return;
    }

    printf("\n[成功] 已分配车位: 第%d层 第%d号位\n", spot.level + 1, spot.position + 1);
    printf("[票号] %d (取车时请提供此票号)\n", ticket);

    cli_print_sequence(&seq);

    sm_handle_event(&sys->sm, EVENT_MOVE_COMPLETE, ticket);

    logger_record(&sys->logger, LOG_PARK, ticket,
                  "车牌%s %s型 -> 第%d层第%d号位",
                  plate, size == VEHICLE_SMALL ? "小" : "大",
                  spot.level + 1, spot.position + 1);

    for (int i = 0; i < sys->garage.vehicle_count; i++) {
        Vehicle *tv = &sys->garage.vehicles[i];
        if (tv->is_temp_moved && tv->is_parked) {
            int temp_pos = tv->position;
            int orig_pos = tv->original_position;
            int lv = tv->level;

            sys->garage.spots[lv][temp_pos].occupied = false;
            sys->garage.spots[lv][temp_pos].vehicle_id = -1;
            sys->garage.spots[lv][orig_pos].occupied = true;
            sys->garage.spots[lv][orig_pos].vehicle_id = tv->id;
            tv->position = orig_pos;
            tv->is_temp_moved = false;

            logger_record(&sys->logger, LOG_MOVE, tv->id,
                          "归位: 车牌%s 从(%d层,%d号) -> (%d层,%d号)",
                          tv->plate, lv + 1, temp_pos + 1, lv + 1, orig_pos + 1);
        }
    }
}

void cli_handle_retrieve(ParkingSystem *sys) {
    if (sm_get_state(&sys->sm) != STATE_IDLE) {
        printf("[错误] 系统忙，请稍后再试。当前状态: %s\n", sm_state_name(sm_get_state(&sys->sm)));
        return;
    }

    int ticket;
    printf("请输入票号: ");
    if (scanf("%d", &ticket) != 1) {
        printf("[错误] 输入无效\n");
        while (getchar() != '\n');
        return;
    }

    Vehicle *v = garage_find_vehicle_by_ticket(&sys->garage, ticket);
    if (!v) {
        printf("[错误] 未找到该票号对应的车辆！\n");
        return;
    }

    printf("\n[信息] 正在取出车辆: %s (第%d层 第%d号位)\n",
           v->plate, v->level + 1, v->position + 1);

    sm_handle_event(&sys->sm, EVENT_RETRIEVE_REQUEST, ticket);

    MovementSequence seq;
    ErrorCode err = planner_plan_retrieve(&sys->garage, ticket, &seq);
    if (err != ERR_OK) {
        printf("[错误] 取车路径规划失败！\n");
        sm_handle_event(&sys->sm, EVENT_ERROR_OCCURRED, ticket);
        logger_record(&sys->logger, LOG_ERROR, ticket, "取车路径规划失败");
        return;
    }

    cli_print_sequence(&seq);

    BillRecord bill;
    v->exit_time = time(NULL);
    billing_generate_record(v, &bill);
    billing_print_receipt(&bill);

    logger_record(&sys->logger, LOG_RETRIEVE, ticket,
                  "车牌%s 取车成功, 时长%d分钟, 费用%.2f元",
                  v->plate, bill.duration_minutes, bill.fee);
    logger_record(&sys->logger, LOG_BILLING, ticket,
                  "计费: %.2f元 (%s型, %d分钟)",
                  bill.fee, v->size == VEHICLE_SMALL ? "小" : "大", bill.duration_minutes);

    garage_remove_vehicle(&sys->garage, ticket);

    for (int i = 0; i < sys->garage.vehicle_count; i++) {
        Vehicle *tv = &sys->garage.vehicles[i];
        if (tv->is_temp_moved && tv->is_parked) {
            int temp_pos = tv->position;
            int orig_pos = tv->original_position;
            int lv = tv->level;

            sys->garage.spots[lv][temp_pos].occupied = false;
            sys->garage.spots[lv][temp_pos].vehicle_id = -1;
            sys->garage.spots[lv][orig_pos].occupied = true;
            sys->garage.spots[lv][orig_pos].vehicle_id = tv->id;
            tv->position = orig_pos;
            tv->is_temp_moved = false;

            logger_record(&sys->logger, LOG_MOVE, tv->id,
                          "归位: 车牌%s 从(%d层,%d号) -> (%d层,%d号)",
                          tv->plate, lv + 1, temp_pos + 1, lv + 1, orig_pos + 1);
        }
    }

    sm_handle_event(&sys->sm, EVENT_MOVE_COMPLETE, ticket);
}

void cli_run(ParkingSystem *sys) {
    int choice;
    int running = 1;

    printf("\n");
    printf("========================================\n");
    printf("   智能立体车库系统 v1.0 启动完成\n");
    printf("   3层 x 5车位, 升降横移式\n");
    printf("========================================\n");

    while (running) {
        cli_show_menu(sys);

        if (scanf("%d", &choice) != 1) {
            printf("[错误] 请输入有效数字\n");
            while (getchar() != '\n');
            continue;
        }

        switch (choice) {
        case 1:
            cli_handle_park(sys);
            break;
        case 2:
            cli_handle_retrieve(sys);
            break;
        case 3:
            garage_display_status(&sys->garage);
            break;
        case 4:
            logger_display(&sys->logger, 20);
            break;
        case 0:
            printf("\n系统关闭中...\n");
            running = 0;
            break;
        default:
            printf("[错误] 无效指令，请重新输入\n");
            break;
        }
    }
}
