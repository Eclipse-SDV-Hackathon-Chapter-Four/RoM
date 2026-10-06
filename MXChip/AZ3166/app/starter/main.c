/* 
 * Copyright (c) Microsoft
 * Copyright (c) 2024 Eclipse Foundation
 * 
 *  This program and the accompanying materials are made available 
 *  under the terms of the MIT license which is available at
 *  https://opensource.org/license/mit.
 * 
 *  SPDX-License-Identifier: MIT
 * 
 *  Contributors: 
 *     Microsoft         - Initial version
 *     Frédéric Desbiens - 2024 version.
 */

#include <stdio.h>

#include "tx_api.h"

#include "board_init.h"
#include "cmsis_utils.h"
#include "nanoprintf.h"
#include "screen.h"
#include "sensor.h"
#include "sntp_client.h"
#include "wwd_networking.h"

#include "cloud_config.h"

#define ECLIPSETX_THREAD_STACK_SIZE 4096
#define ECLIPSETX_THREAD_PRIORITY   4

#define SENSOR_READ_INTERVAL_SEC 2

TX_THREAD eclipsetx_thread;
TX_THREAD eclipsetx_thread2;
ULONG eclipsetx_thread_stack[ECLIPSETX_THREAD_STACK_SIZE / sizeof(ULONG)];
ULONG eclipsetx_thread_stack2[ECLIPSETX_THREAD_STACK_SIZE / sizeof(ULONG)];


static void eclipsetx_thread_entry(ULONG parameter)
{
    UINT status;

    printf("Starting Eclipse ThreadX thread\r\n\r\n");

    // Initialize the network
    if ((status = wwd_network_init(WIFI_SSID, WIFI_PASSWORD, WIFI_MODE)))
    {
        printf("ERROR: Failed to initialize the network (0x%08x)\r\n", status);
    }

     wwd_network_connect();
}

static void sensor_thread_entry(ULONG parameter)
{
    char l0[22], l1[22], l2[22], l3[22];
    const char* lines[4] = { l0, l1, l2, l3 };

    printf("Starting sensor thread\r\n\r\n");

    while (1)
    {
        hts221_data_t ht   = hts221_data_read();
        lps22hb_t     pres = lps22hb_data_read();
        lsm6dsl_data_t acc = lsm6dsl_data_read();
        lis2mdl_data_t mag = lis2mdl_data_read();

        // Standard snprintf/printf on this target are built without float
        // support (newlib-nano), so float formatting must go through
        // nanoprintf's own npf_snprintf instead.
        npf_snprintf(l0, sizeof(l0), "T:%.1fC H:%.0f%%", (double)ht.temperature_degC, (double)ht.humidity_perc);
        npf_snprintf(l1, sizeof(l1), "P:%.0fhPa", (double)pres.pressure_hPa);
        npf_snprintf(l2, sizeof(l2), "A:%.0f,%.0f,%.0f", (double)acc.acceleration_mg[0], (double)acc.acceleration_mg[1], (double)acc.acceleration_mg[2]);
        npf_snprintf(l3, sizeof(l3), "M:%.0f,%.0f,%.0f", (double)mag.magnetic_mG[0], (double)mag.magnetic_mG[1], (double)mag.magnetic_mG[2]);

        screen_print_small(lines, 4);

        char serial_line[128];
        npf_snprintf(serial_line, sizeof(serial_line),
            "T=%.1fC H=%.0f%% P=%.0fhPa Acc(mg)=[%.0f,%.0f,%.0f] Mag(mG)=[%.0f,%.0f,%.0f]\r\n",
            (double)ht.temperature_degC, (double)ht.humidity_perc, (double)pres.pressure_hPa,
            (double)acc.acceleration_mg[0], (double)acc.acceleration_mg[1], (double)acc.acceleration_mg[2],
            (double)mag.magnetic_mG[0], (double)mag.magnetic_mG[1], (double)mag.magnetic_mG[2]);
        printf("%s", serial_line);

        tx_thread_sleep(TX_TIMER_TICKS_PER_SECOND * SENSOR_READ_INTERVAL_SEC);
    }
}

void tx_application_define(void* first_unused_memory)
{
    systick_interval_set(TX_TIMER_TICKS_PER_SECOND);

    // Create ThreadX thread
    UINT status = tx_thread_create(&eclipsetx_thread,
        "Eclipse ThreadX Thread",
        eclipsetx_thread_entry,
        0,
        eclipsetx_thread_stack,
        ECLIPSETX_THREAD_STACK_SIZE,
        ECLIPSETX_THREAD_PRIORITY,
        ECLIPSETX_THREAD_PRIORITY,
        TX_NO_TIME_SLICE,
        TX_AUTO_START);

    if (status != TX_SUCCESS)
    {
        printf("ERROR: Eclipse ThreadX thread creation failed\r\n");
    }

    // Create sensor display thread
    status = tx_thread_create(&eclipsetx_thread2,
        "Sensor Thread",
        sensor_thread_entry,
        0,
        eclipsetx_thread_stack2,
        ECLIPSETX_THREAD_STACK_SIZE,
        ECLIPSETX_THREAD_PRIORITY,
        ECLIPSETX_THREAD_PRIORITY,
        TX_NO_TIME_SLICE,
        TX_AUTO_START);

    if (status != TX_SUCCESS)
    {
        printf("ERROR: Sensor thread creation failed\r\n");
    }
}

int main(void)
{
    // Initialize the board
    board_init();

    // Enter the ThreadX kernel
    tx_kernel_enter();

    return 0;
}
