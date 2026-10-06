/* 
 *  Copyright (c) 2025 Eclipse Foundation
 * 
 *  This program and the accompanying materials are made available 
 *  under the terms of the MIT license which is available at
 *  https://opensource.org/license/mit.
 * 
 *  SPDX-License-Identifier: MIT
 * 
 *  Contributors: 
 *     Frédéric Desbiens - Initial version.
 */

#include "cloud_config.h"
#include "display_cmd.h"
#include "nanoprintf.h"
#include "screen.h"
#include "sensor.h"
#include "sntp_client.h"
#include "telemetry.h"
#include <stdio.h>

// Sensor message sequence number (per boot, starts at 1: the adapter reads a drop as a device reboot)
static uint32_t telemetry_seq = 0;

// Current data
static sensor_data current_sensor_data;

const int TELEMETRY_BUFFER_SIZE = 256;

#ifdef LOG_TELEMETRY
// Human-readable dump of all sensors, only for debugging on the serial console.
static const int TELEMETRY_ROWS        = 5;
static const int TELEMETRY_ROW_SIZE    = 40;

static void get_sensor_data_buffer(sensor_data data, char* output){
    char buf[TELEMETRY_ROWS][TELEMETRY_ROW_SIZE];
    npf_snprintf(buf[0], TELEMETRY_ROW_SIZE, "Pressure: %.2f\r\n", (double)data.pressure_hPa);
    npf_snprintf(buf[1], TELEMETRY_ROW_SIZE, "Temperature: %.2f\r\n", (double)data.temperature_degC);
    npf_snprintf(buf[2], TELEMETRY_ROW_SIZE, "Humidity: %.2f\r\n", (double)data.humidity_perc);
    npf_snprintf(buf[3], TELEMETRY_ROW_SIZE, "Acceleration: %.2f, %.2f, %.2f\r\n", 
                                                    (double)data.acceleration_mg[0],
                                                    (double)data.acceleration_mg[1],
                                                    (double)data.acceleration_mg[2]);
    npf_snprintf(buf[4], TELEMETRY_ROW_SIZE, "Magnetic: %.2f, %.2f, %.2f\r\n", 
                                                (double)data.magnetic_mG[0],
                                                (double)data.magnetic_mG[1],
                                                (double)data.magnetic_mG[2]);

    // Initialize the new array with an empty string.
    output[0] = '\0';

    // Concatenate the strings from the 2D array.
    for (int i = 0; i < TELEMETRY_ROWS; i++) {
        strcat(output, buf[i]);
    }
}
#endif

/** 
 * Only used if LOG_TELEMETRY is defined. 
 * 
 * Uncomment the definition in telemetry.h if needed.
 */
#ifdef LOG_TELEMETRY
static void print_sensor_data(sensor_data data){
    char data_string[TELEMETRY_BUFFER_SIZE];
    get_sensor_data_buffer(data, data_string);
    printf("=====\r\n");
    printf("%s", data_string);   
    printf("=====\r\n\r\n");
}
#endif

/**
 * Entry point for the telemetry thread.
 */
void telemetry_thread_entry(ULONG parameter)
{
    //UINT status;
    sensor_data new_sensor_data;
    char l0[22], l1[22], l2[22], l3[22], l4[22], l5[22], l6[22];
    const char* lines[7] = { l0, l1, l2, l3, l4, l5, l6 };

    printf("Starting telemetry thread\r\n\r\n");

    while(1){

        // Acquire fresh data.
        lps22hb_t lps22hb_data = lps22hb_data_read();
        new_sensor_data.temperature_degC = lps22hb_data.temperature_degC;
        new_sensor_data.pressure_hPa = lps22hb_data.pressure_hPa;
        hts221_data_t hts221_data = hts221_data_read();
        new_sensor_data.humidity_perc = hts221_data.humidity_perc;
        lsm6dsl_data_t lsm6dsl_data = lsm6dsl_data_read();
        memcpy(new_sensor_data.acceleration_mg, 
               lsm6dsl_data.acceleration_mg,
               sizeof(lsm6dsl_data.acceleration_mg));
        lis2mdl_data_t lis2mdl_data = lis2mdl_data_read();
        memcpy(new_sensor_data.magnetic_mG, 
               lis2mdl_data.magnetic_mG,
               sizeof(lis2mdl_data.magnetic_mG));

        // Update the OLED with the readings just acquired (npf_snprintf: no float support in snprintf).
        npf_snprintf(l0, sizeof(l0), "T:%.1fC H:%.0f%%", (double)new_sensor_data.temperature_degC, (double)new_sensor_data.humidity_perc);
        npf_snprintf(l1, sizeof(l1), "P:%.0fhPa", (double)new_sensor_data.pressure_hPa);
        npf_snprintf(l2, sizeof(l2), "A:%.0f,%.0f,%.0f", (double)new_sensor_data.acceleration_mg[0], (double)new_sensor_data.acceleration_mg[1], (double)new_sensor_data.acceleration_mg[2]);
        npf_snprintf(l3, sizeof(l3), "M:%.0f,%.0f,%.0f", (double)new_sensor_data.magnetic_mG[0], (double)new_sensor_data.magnetic_mG[1], (double)new_sensor_data.magnetic_mG[2]);

        // Lines 5-7: guardian state from rom/actuator/display/cmd (state, temp_c, reason).
        display_cmd_t guardian;
        bool guardian_stale = false;
        if (!display_cmd_load(&guardian, &guardian_stale)){
            npf_snprintf(l4, sizeof(l4), "GUARDIAN: waiting");
            l5[0] = '\0';
            l6[0] = '\0';
        }
        else if (guardian_stale){
            npf_snprintf(l4, sizeof(l4), "G:NO LINK");
            npf_snprintf(l5, sizeof(l5), "last:%s", guardian.state);
            l6[0] = '\0';
        }
        else{
            npf_snprintf(l4, sizeof(l4), "G:%s", guardian.state);
            if (guardian.has_temp){
                npf_snprintf(l5, sizeof(l5), "T:%.2fC", (double)guardian.temp_c);
            }
            else{
                npf_snprintf(l5, sizeof(l5), "T:--");
            }
            npf_snprintf(l6, sizeof(l6), "%s", guardian.reason);
        }
        screen_print_small(lines, 7);

        // The RoM contract is a fixed-period stream: publish every cycle, changed or not
        // (the guardian flags a signal as stale after 2 s without messages).
        current_sensor_data = new_sensor_data;
        #ifdef LOG_TELEMETRY
            print_sensor_data(new_sensor_data);
        #endif
        tx_event_flags_set(&mqtt_app_flag, MQTT_MESSAGE_READY, TX_OR);

        tx_thread_sleep((TX_TIMER_TICKS_PER_SECOND * TELEMETRY_INTERVAL_MS) / 1000);
    }
}

/**
 * Builds {"device_id":...,"seq":...,"ts_ms":...,"temp_c":...} (common/contracts.py build_sensor_msg).
 *
 * ts_ms is epoch milliseconds once SNTP has synced, uptime milliseconds before (the adapter treats
 * values below 1e12 as uptime). npf_snprintf has no 64-bit support, so ts_ms is printed in two parts.
 */
size_t telemetry_build_sensor_msg(char* out, size_t out_size){
    uint64_t ts_ms = sntp_time_ms_get();
    uint32_t ts_hi = (uint32_t)(ts_ms / 1000000000u);
    uint32_t ts_lo = (uint32_t)(ts_ms % 1000000000u);
    char ts[24];

    if (ts_hi > 0){
        npf_snprintf(ts, sizeof(ts), "%u%09u", (unsigned)ts_hi, (unsigned)ts_lo);
    }
    else{
        npf_snprintf(ts, sizeof(ts), "%u", (unsigned)ts_lo);
    }

    int n = npf_snprintf(out, out_size, "{\"device_id\":\"%s\",\"seq\":%u,\"ts_ms\":%s,\"temp_c\":%.2f}",
                         MQTT_DEVICE_ID, (unsigned)++telemetry_seq, ts, (double)current_sensor_data.temperature_degC);

    return (n > 0 && (size_t)n < out_size) ? (size_t)n : 0;
}
