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
#include "sensor.h"
#include "tx_api.h"
#include <math.h>
#include <stdint.h>
#include <stdio.h>

#ifndef _TELEMETRY_H
#define _TELEMETRY_H

// Log telemetry if needed
//#define LOG_TELEMETRY

// Sensor data
typedef struct{
    float pressure_hPa;
    float temperature_degC;
    float humidity_perc;
    float acceleration_mg[3];
    float magnetic_mG[3];
} sensor_data;

void telemetry_thread_entry(ULONG parameter);
/* Builds the next RoM sensor message (common/contracts.py build_sensor_msg) into out.
 * Increments seq. Returns the length, or 0 if out is too small. */
size_t telemetry_build_sensor_msg(char* out, size_t out_size);

#endif // _TELEMETRY_H