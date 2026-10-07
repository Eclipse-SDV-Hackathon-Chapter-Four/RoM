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

#ifndef _CLOUD_CONFIG_H
#define _CLOUD_CONFIG_H

#include "nx_api.h"

typedef enum
{
    None         = 0,
    WEP          = 1,
    WPA_PSK_TKIP = 2,
    WPA2_PSK_AES = 3
} WiFi_Mode;

// ----------------------------------------------------------------------------
// WiFi connection config
// ----------------------------------------------------------------------------
#define HOSTNAME      "az3166-hackathon"  //Change to unique hostname.
// Credentials live in cloud_config_local.h (git-ignored, never commit it). Create it next to this
// file with your own values, e.g.:
//   #define WIFI_SSID     "your-ssid"
//   #define WIFI_PASSWORD "your-password"
#if defined(__has_include)
#if __has_include("cloud_config_local.h")
#include "cloud_config_local.h"
#endif
#endif
#ifndef WIFI_SSID
#define WIFI_SSID     ""   // Fill in locally. Do not commit real credentials.
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""   // Fill in locally. Do not commit real credentials.
#endif
#define WIFI_MODE     WPA2_PSK_AES

// ----------------------------------------------------------------------------
// MQTT Config
// ----------------------------------------------------------------------------
#define MQTT_CLIENT_NAME     "ThreadXAZ3166" //Change to unique name if you run multiple boards.
// IP of the Mosquitto broker on your hackathon LAN. See README for how to set one up.
#define MQTT_LOCAL_BROKER_IP (IP_ADDRESS(192, 168, 88, 250))
// Unique per board: two clients with the same ID kick each other off the broker.
#define MQTT_CLIENT_ID       MQTT_CLIENT_NAME "-mery"
// On-demand request topic (not part of the RoM contract): any message triggers an immediate publish.
#define MQTT_SUBSCRIBE_TOPIC MQTT_CLIENT_NAME "/incoming" 

// RoM contract (common/contracts.py): sensor message QoS 0 no retain, status QoS 1 retain (LWT).
// Keep in sync with TOPIC_SENSOR_TEMP / TOPIC_SENSOR_STATUS.
#define MQTT_PUBLISH_TOPIC   "rom/sensor/battery/temp"
#define MQTT_STATUS_TOPIC    "rom/sensor/battery/status"
// Guardian state for the OLED (TOPIC_DISPLAY_CMD, QoS 1, retained). See display_cmd.h for the payload.
#define MQTT_DISPLAY_TOPIC   "rom/actuator/display/cmd"
#define MQTT_STATUS_ONLINE   "online"
#define MQTT_STATUS_OFFLINE  "offline"
// device_id in every sensor message; the adapter tracks seq per device_id, so keep it unique per board.
#define MQTT_DEVICE_ID       "az3166-01"
// Sensor message period in milliseconds.
#define TELEMETRY_INTERVAL_MS 500

// ----------------------------------------------------------------------------
// MQTT Support infrastructure
// ----------------------------------------------------------------------------
extern TX_QUEUE mqtt_queue;
extern TX_EVENT_FLAGS_GROUP mqtt_app_flag;
#define MQTT_RECEIVE_EVENT    1
#define MQTT_MESSAGE_READY    2
#define MQTT_DISCONNECT_EVENT 4  // set when the broker connection is lost: the MQTT thread reconnects
#define MQTT_ALL_EVENTS       7


#endif // _CLOUD_CONFIG_H
