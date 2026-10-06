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
#define MQTT_SUBSCRIBE_TOPIC MQTT_CLIENT_NAME "/incoming" 
#define MQTT_PUBLISH_TOPIC   MQTT_CLIENT_NAME "/telemetry" 

// ----------------------------------------------------------------------------
// MQTT Support infrastructure
// ----------------------------------------------------------------------------
extern TX_QUEUE mqtt_queue;
extern TX_EVENT_FLAGS_GROUP mqtt_app_flag;
#define MQTT_RECEIVE_EVENT 1
#define MQTT_MESSAGE_READY 2
#define MQTT_ALL_EVENTS    3


#endif // _CLOUD_CONFIG_H
