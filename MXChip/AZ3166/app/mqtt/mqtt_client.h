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
 
#include "nxd_mqtt_client.h"

#ifndef MQTT_CLIENT_H
#define MQTT_CLIENT_H
/* Declare event flag, which is used in this demo. */
#endif

#undef  NXD_MQTT_MAX_TOPIC_NAME_LENGTH
#undef  NXD_MQTT_MAX_MESSAGE_LENGTH
#define NXD_MQTT_MAX_TOPIC_NAME_LENGTH 70
#define NXD_MQTT_MAX_MESSAGE_LENGTH 170

#define MQTT_CLIENT_STACK_SIZE 5120


void mqtt_thread_entry(ULONG thread_input);

/* Define the symbol for signaling a received message. */

/* Define the priority of the MQTT internal thread. */
#define MQTT_THREAD_PRIORTY 2

/* MQTT keep alive in seconds. Short on purpose: the broker publishes the LWT ("offline") after
 * 1.5x this value without traffic, and the guardian relies on it to tell "sensor offline" from stale. */
#define MQTT_KEEP_ALIVE_TIMER 10

#define QOS0 0
#define QOS1 1
