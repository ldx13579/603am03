#include "simulation.h"
#include "path_planner.h"
#include "billing.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static const EntranceConfig default_entrances[NUM_ENTRANCES] = {
    {0, 0},
    {1, 2},
    {2, 4}
};

/* ─── Spot lock grid ─── */

void spot_grid_init(SpotLockGrid *sg) {
    for (int lv = 0; lv < NUM_LEVELS; lv++) {
        for (int pos = 0; pos < SPOTS_PER_LEVEL; pos++) {
            mutex_init(&sg->spots[lv][pos]);
        }
    }
    mutex_init(&sg->lift_lock);
}

void spot_grid_destroy(SpotLockGrid *sg) {
    for (int lv = 0; lv < NUM_LEVELS; lv++) {
        for (int pos = 0; pos < SPOTS_PER_LEVEL; pos++) {
            mutex_destroy(&sg->spots[lv][pos]);
        }
    }
    mutex_destroy(&sg->lift_lock);
}

static void lock_spot_path(SpotLockGrid *sg, int level, int position) {
    mutex_lock(&sg->lift_lock);
    if (level > 0) {
        mutex_lock(&sg->spots[0][LIFT_COLUMN]);
        mutex_lock(&sg->spots[level][LIFT_COLUMN]);
    }
    if (position != LIFT_COLUMN) {
        mutex_lock(&sg->spots[level][position]);
    }
}

static void unlock_spot_path(SpotLockGrid *sg, int level, int position) {
    if (position != LIFT_COLUMN) {
        mutex_unlock(&sg->spots[level][position]);
    }
    if (level > 0) {
        mutex_unlock(&sg->spots[level][LIFT_COLUMN]);
        mutex_unlock(&sg->spots[0][LIFT_COLUMN]);
    }
    mutex_unlock(&sg->lift_lock);
}

/* ─── Utility ─── */

static unsigned int thread_lcg(unsigned int *seed) {
    *seed = (*seed) * 1103515245u + 12345u;
    return (*seed >> 16) & 0x7FFF;
}

static int random_range(unsigned int *seed, int min_val, int max_val) {
    if (min_val >= max_val) return min_val;
    unsigned int r = thread_lcg(seed);
    return min_val + (int)(r % (unsigned int)(max_val - min_val + 1));
}

static void generate_plate(unsigned int *seed, char *plate, int max_len) {
    const char *prefixes[] = {"京A", "沪B", "粤C", "浙D", "苏E"};
    int prefix_idx = random_range(seed, 0, 4);
    int num = random_range(seed, 1000, 9999);
    snprintf(plate, max_len, "%s%d", prefixes[prefix_idx], num);
}

static int get_sim_hour(time_t start, int duration_s) {
    double elapsed = difftime(time(NULL), start);
    if (duration_s <= 0) return 0;
    int hour = (int)((elapsed / (double)duration_s) * 24.0);
    if (hour < 0) hour = 0;
    if (hour >= 24) hour = 23;
    return hour;
}

static Vehicle *pick_random_vehicle(Garage *g, unsigned int *seed) {
    int parked_count = 0;
    for (int i = 0; i < g->vehicle_count; i++) {
        if (g->vehicles[i].is_parked && !g->vehicles[i].is_temp_moved &&
            g->vehicles[i].state != VSTATE_RETRIEVING_PREPARE) {
            parked_count++;
        }
    }
    if (parked_count == 0) return NULL;

    int pick = random_range(seed, 0, parked_count - 1);
    int idx = 0;
    for (int i = 0; i < g->vehicle_count; i++) {
        if (g->vehicles[i].is_parked && !g->vehicles[i].is_temp_moved &&
            g->vehicles[i].state != VSTATE_RETRIEVING_PREPARE) {
            if (idx == pick) return &g->vehicles[i];
            idx++;
        }
    }
    return NULL;
}

/* ─── Movement execution with fine-grained locking ─── */

typedef struct {
    bool     success;
    bool     fault_occurred;
    int      steps_executed;
} ExecResult;

static ExecResult execute_movements(EntranceThreadArg *ctx, MovementSequence *seq,
                                    int level, int position) {
    ExecResult result = {true, false, 0};

    lock_spot_path(ctx->spot_grid, level, position);

    int sim_hour = get_sim_hour(ctx->sim_start_time, ctx->config->simulation_duration_s);

    for (int i = 0; i < seq->count; i++) {
        if (*ctx->stop_flag) break;

        Sleep(MOVEMENT_STEP_MS);
        result.steps_executed++;
        stats_record_movement(ctx->stats, sim_hour, 1);

        FaultResult fr = fault_execute_step(&ctx->fault_cfg);
        if (fr.failed) {
            result.fault_occurred = true;
            if (fr.final_success) {
                stats_record_fault(ctx->stats, true);
                logger_record(ctx->logger, LOG_FAULT, ctx->entrance_id,
                              "入口%d: 步骤%d故障, 重试%d次(%dms退避)后恢复",
                              ctx->entrance_id + 1, i + 1, fr.retry_count, fr.total_backoff_ms);
            } else {
                stats_record_fault(ctx->stats, false);
                logger_record(ctx->logger, LOG_FAULT, ctx->entrance_id,
                              "入口%d: 步骤%d机械故障, 重试%d次(%dms退避)失败, 操作回滚",
                              ctx->entrance_id + 1, i + 1, fr.retry_count, fr.total_backoff_ms);
                result.success = false;
                unlock_spot_path(ctx->spot_grid, level, position);
                return result;
            }
        }
    }

    unlock_spot_path(ctx->spot_grid, level, position);
    return result;
}

/* ─── Entrance thread ─── */

static unsigned __stdcall entrance_thread_func(void *arg) {
    EntranceThreadArg *ctx = (EntranceThreadArg *)arg;
    unsigned int rng_seed = (unsigned int)(ctx->entrance_id * 7919 + (unsigned int)time(NULL));

    printf("[入口%d] 线程启动, 位于地面位置%d\n", ctx->entrance_id + 1, ctx->entrance_cfg.ground_position + 1);

    while (!*ctx->stop_flag) {
        int delay = random_range(&rng_seed, ctx->config->min_request_interval_ms,
                                 ctx->config->max_request_interval_ms);
        Sleep(delay);

        if (*ctx->stop_flag) break;

        int sim_hour = get_sim_hour(ctx->sim_start_time, ctx->config->simulation_duration_s);

        /* Read-lock to check occupancy */
        rwlock_read_lock(ctx->garage_rwlock);
        int free_count = garage_count_free(ctx->garage, VEHICLE_SMALL);
        int parked_count = 0;
        for (int i = 0; i < ctx->garage->vehicle_count; i++) {
            if (ctx->garage->vehicles[i].is_parked && !ctx->garage->vehicles[i].is_temp_moved)
                parked_count++;
        }
        rwlock_read_unlock(ctx->garage_rwlock);

        bool do_park;
        if (parked_count == 0) {
            do_park = true;
        } else if (free_count == 0) {
            do_park = false;
        } else {
            do_park = (random_range(&rng_seed, 0, 99) < 60);
        }

        LARGE_INTEGER freq, t_start, t_end;
        QueryPerformanceFrequency(&freq);
        QueryPerformanceCounter(&t_start);

        if (do_park) {
            VehicleSize size = (random_range(&rng_seed, 0, 99) < 70) ? VEHICLE_SMALL : VEHICLE_LARGE;
            char plate[16];
            generate_plate(&rng_seed, plate, sizeof(plate));

            /* Phase 1: PREPARE — write-lock, plan, reserve and register vehicle */
            rwlock_write_lock(ctx->garage_rwlock);

            SpotLocation spot;
            ErrorCode err = scheduler_assign_spot(ctx->garage, size,
                                                  ctx->entrance_id, ctx->all_entrances, &spot);
            if (err != ERR_OK) {
                rwlock_write_unlock(ctx->garage_rwlock);
                continue;
            }

            garage_reserve_spot(ctx->garage, spot.level, spot.position);

            MovementSequence seq;
            err = planner_plan_park(ctx->garage, spot, &seq);
            if (err != ERR_OK) {
                garage_unreserve_spot(ctx->garage, spot.level, spot.position);
                rwlock_write_unlock(ctx->garage_rwlock);
                continue;
            }

            int ticket = garage_prepare_park(ctx->garage, plate, size, spot.level, spot.position);
            if (ticket < 0) {
                garage_unreserve_spot(ctx->garage, spot.level, spot.position);
                rwlock_write_unlock(ctx->garage_rwlock);
                continue;
            }

            rwlock_write_unlock(ctx->garage_rwlock);

            /* Physical movement with fine-grained spot lock */
            ExecResult er = execute_movements(ctx, &seq, spot.level, spot.position);

            /* Phase 2: COMMIT or ABORT */
            rwlock_write_lock(ctx->garage_rwlock);
            if (!er.success) {
                garage_abort_park(ctx->garage, ticket);
                planner_restore_all_temp(ctx->garage, ctx->logger);
                rwlock_write_unlock(ctx->garage_rwlock);
                continue;
            }
            garage_commit_park(ctx->garage, ticket);
            planner_execute_restore(ctx->garage, &seq, ctx->logger);
            rwlock_write_unlock(ctx->garage_rwlock);

            QueryPerformanceCounter(&t_end);
            double duration_ms = (double)(t_end.QuadPart - t_start.QuadPart) * 1000.0 / freq.QuadPart;
            stats_record_park(ctx->stats, sim_hour, duration_ms);

            logger_record(ctx->logger, LOG_PARK, ticket,
                          "入口%d: 车牌%s %s型 -> 第%d层第%d号位",
                          ctx->entrance_id + 1, plate,
                          size == VEHICLE_SMALL ? "小" : "大",
                          spot.level + 1, spot.position + 1);

        } else {
            /* Phase 1: PREPARE — write-lock, plan, mark vehicle as retrieving */
            rwlock_write_lock(ctx->garage_rwlock);

            Vehicle *v = pick_random_vehicle(ctx->garage, &rng_seed);
            if (!v) {
                rwlock_write_unlock(ctx->garage_rwlock);
                continue;
            }

            int ticket = v->id;
            int vlevel = v->level;
            int vpos = v->position;
            char vplate[16];
            strncpy(vplate, v->plate, sizeof(vplate) - 1);
            vplate[sizeof(vplate) - 1] = '\0';

            garage_prepare_retrieve(ctx->garage, ticket);

            MovementSequence seq;
            ErrorCode err = planner_plan_retrieve(ctx->garage, ticket, &seq);
            if (err != ERR_OK) {
                garage_abort_retrieve(ctx->garage, ticket);
                rwlock_write_unlock(ctx->garage_rwlock);
                continue;
            }

            rwlock_write_unlock(ctx->garage_rwlock);

            /* Physical movement with fine-grained spot lock */
            ExecResult er = execute_movements(ctx, &seq, vlevel, vpos);

            /* Phase 2: COMMIT or ABORT */
            rwlock_write_lock(ctx->garage_rwlock);
            if (!er.success) {
                garage_abort_retrieve(ctx->garage, ticket);
                planner_restore_all_temp(ctx->garage, ctx->logger);
                rwlock_write_unlock(ctx->garage_rwlock);
                continue;
            }
            garage_commit_retrieve(ctx->garage, ticket);
            planner_execute_restore(ctx->garage, &seq, ctx->logger);
            rwlock_write_unlock(ctx->garage_rwlock);

            QueryPerformanceCounter(&t_end);
            double duration_ms = (double)(t_end.QuadPart - t_start.QuadPart) * 1000.0 / freq.QuadPart;
            stats_record_retrieve(ctx->stats, sim_hour, duration_ms);

            logger_record(ctx->logger, LOG_RETRIEVE, ticket,
                          "入口%d: 车牌%s 取车完成", ctx->entrance_id + 1, vplate);
        }
    }

    printf("[入口%d] 线程结束\n", ctx->entrance_id + 1);
    return 0;
}

/* ─── Configuration ─── */

void sim_config_default(SimConfig *cfg) {
    cfg->num_entrances = NUM_ENTRANCES;
    cfg->simulation_duration_s = 30;
    cfg->fault_probability = 0.05;
    cfg->fault_max_retries = 3;
    cfg->min_request_interval_ms = 500;
    cfg->max_request_interval_ms = 2000;
}

void sim_print_config(const SimConfig *cfg) {
    printf("\n");
    printf("============== 仿真配置 ==============\n");
    printf("  入口数量:     %d\n", cfg->num_entrances);
    printf("  仿真时长:     %d 秒\n", cfg->simulation_duration_s);
    printf("  故障概率:     %.1f%%\n", cfg->fault_probability * 100.0);
    printf("  最大重试:     %d 次\n", cfg->fault_max_retries);
    printf("  请求间隔:     %d-%d ms\n", cfg->min_request_interval_ms, cfg->max_request_interval_ms);
    printf("======================================\n\n");
}

/* ─── Main simulation loop ─── */

void sim_run(SimConfig *cfg) {
    printf("\n");
    printf("╔══════════════════════════════════════════════╗\n");
    printf("║   多入口仿真模式 启动中...                  ║\n");
    printf("╚══════════════════════════════════════════════╝\n");

    sim_print_config(cfg);

    Garage garage;
    garage_init(&garage);

    Logger logger;
    logger_init_threadsafe(&logger);

    Statistics stats;
    stats_init(&stats);

    RWLock garage_rwlock;
    rwlock_init(&garage_rwlock);

    SpotLockGrid spot_grid;
    spot_grid_init(&spot_grid);

    volatile bool stop_flag = false;
    time_t sim_start = time(NULL);

    EntranceConfig entrances[NUM_ENTRANCES];
    memcpy(entrances, default_entrances, sizeof(entrances));

    EntranceThreadArg thread_args[NUM_ENTRANCES];
    Thread threads[NUM_ENTRANCES];

    for (int i = 0; i < cfg->num_entrances; i++) {
        thread_args[i].entrance_id = i;
        thread_args[i].entrance_cfg = entrances[i];
        fault_config_init(&thread_args[i].fault_cfg, cfg->fault_probability, cfg->fault_max_retries);
        fault_set_seed(&thread_args[i].fault_cfg, (unsigned int)(i * 13 + (unsigned int)time(NULL)));
        thread_args[i].garage = &garage;
        thread_args[i].logger = &logger;
        thread_args[i].stats = &stats;
        thread_args[i].spot_grid = &spot_grid;
        thread_args[i].garage_rwlock = &garage_rwlock;
        thread_args[i].stop_flag = &stop_flag;
        thread_args[i].config = cfg;
        thread_args[i].all_entrances = entrances;
        thread_args[i].sim_start_time = sim_start;
    }

    for (int i = 0; i < cfg->num_entrances; i++) {
        threads[i] = thread_create(entrance_thread_func, &thread_args[i]);
    }

    printf("[系统] 仿真运行中... (持续%d秒)\n\n", cfg->simulation_duration_s);
    Sleep(cfg->simulation_duration_s * 1000);

    stop_flag = true;
    printf("\n[系统] 正在停止仿真...\n");

    for (int i = 0; i < cfg->num_entrances; i++) {
        thread_join(threads[i]);
    }

    printf("\n[系统] 所有线程已结束\n");

    printf("\n============== 最终车库状态 ==============\n");
    garage_display_status(&garage);

    printf("\n============== 操作日志 (最近30条) ==============\n");
    logger_display(&logger, 30);

    stats_print_summary(&stats);

    spot_grid_destroy(&spot_grid);
    stats_destroy(&stats);
    logger_destroy(&logger);
}
