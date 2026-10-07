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
#include "mqtt_client.h"
#include "nx_api.h"
#include "telemetry.h"
#include "wwd_networking.h"

#include <stdint.h>
#include <string.h>

// Helper function.
#define STRLEN(p) (sizeof(p) - 1)

/* Declare the MQTT thread stack space. */
static ULONG mqtt_client_stack[MQTT_CLIENT_STACK_SIZE / sizeof(ULONG)];

/* Declare buffers to hold message and topic. */
static UCHAR message_buffer[NXD_MQTT_MAX_MESSAGE_LENGTH];
static UCHAR topic_buffer[NXD_MQTT_MAX_TOPIC_NAME_LENGTH];


/* Declare the MQTT client control block. */
static NXD_MQTT_CLIENT mqtt_client;


/* Declare the disconnect notify function. */
static VOID client_disconnect_func(NXD_MQTT_CLIENT *client_ptr)
{
    NX_PARAMETER_NOT_USED(client_ptr);
    /* Called from inside the MQTT client with its mutex held: do not call the client here, just wake the
     * MQTT thread, which reconnects. */
    tx_event_flags_set(&mqtt_app_flag, MQTT_DISCONNECT_EVENT, TX_OR);
}

static UINT send_message(){
    UINT status;
    
    /* Publish the RoM sensor message: QoS 0, no retain (contract: TOPIC_SENSOR_TEMP). */
    char buffer[160] = {0};
    size_t length = telemetry_build_sensor_msg(buffer, sizeof(buffer));
    if (length == 0){
        printf("Sensor message does not fit the buffer.\r\n");
        return NXD_MQTT_SUCCESS;
    }

    status = nxd_mqtt_client_publish(&mqtt_client, MQTT_PUBLISH_TOPIC, STRLEN(MQTT_PUBLISH_TOPIC),
                                        (CHAR *)buffer, length, 0, QOS0, NX_WAIT_FOREVER);

    if (status != NXD_MQTT_SUCCESS){
        printf("Publish failed with code: %d\r\n", status);
    }
    else{
        printf("Published message.\r\n");
    }

    return status;
}

/* Guardian state for the OLED. Logged only when it changes: the guardian re-sends every second. */
static void handle_display_cmd(const UCHAR *message, UINT length){
    static char last_state[DISPLAY_STATE_MAX];
    static char last_reason[DISPLAY_REASON_MAX];
    display_cmd_t cmd;

    if (!display_cmd_parse((const char *)message, length, &cmd)){
        printf("Ignored invalid display command (%u bytes).\r\n", (unsigned)length);
        return;
    }

    display_cmd_store(&cmd);

    if (strcmp(last_state, cmd.state) != 0 || strcmp(last_reason, cmd.reason) != 0){
        strcpy(last_state, cmd.state);
        strcpy(last_reason, cmd.reason);
        int centi = (int)(cmd.temp_c * 100.0f + (cmd.temp_c < 0 ? -0.5f : 0.5f));
        if (cmd.has_temp){
            printf("Display command: state=%s temp=%d.%02d reason=%s seq=%u\r\n", cmd.state,
                   centi / 100, (centi < 0 ? -centi : centi) % 100, cmd.reason, (unsigned)cmd.seq);
        }
        else{
            printf("Display command: state=%s temp=- reason=%s seq=%u\r\n", cmd.state, cmd.reason, (unsigned)cmd.seq);
        }
    }
}

static void receive_message(){
    UINT status;
    UINT topic_length, message_length;
    ULONG message_sent = 0;

    /* One wake-up can stand for several queued messages: drain them all. */
    while (1){
        status = nxd_mqtt_client_message_get(&mqtt_client, topic_buffer, sizeof(topic_buffer) - 1, &topic_length,
                                            message_buffer, sizeof(message_buffer) - 1, &message_length);

        if (status == NXD_MQTT_INSUFFICIENT_BUFFER_SPACE){
            /* An oversized message stays at the head of the receive queue and would block every later one
             * forever, and message_get cannot discard without a buffer that fits it. Read it into a big buffer
             * just to throw it away. Sized for what the RX packet pool (12 packets of ~1.4 KB) can assemble. */
            static UCHAR drain_buffer[16384];
            status = nxd_mqtt_client_message_get(&mqtt_client, topic_buffer, sizeof(topic_buffer) - 1, &topic_length,
                                                drain_buffer, sizeof(drain_buffer), &message_length);
            printf("Dropped an oversized MQTT message (status %u).\r\n", (unsigned)status);
            if (status != NXD_MQTT_SUCCESS){
                return; /* still stuck: give up until the next event instead of spinning */
            }
            continue;
        }
        if (status != NXD_MQTT_SUCCESS){
            return; /* NXD_MQTT_NO_MESSAGE: queue is empty */
        }

        topic_buffer[topic_length] = 0;
        message_buffer[message_length] = 0;

        if (topic_length == STRLEN(MQTT_DISPLAY_TOPIC) && memcmp(topic_buffer, MQTT_DISPLAY_TOPIC, topic_length) == 0){
            handle_display_cmd(message_buffer, message_length);
            continue;
        }

        /* On-demand request (not part of the RoM contract). Nothing consumes mqtt_queue, so never wait on it:
         * a full queue must not stop this thread. */
        message_sent = message_buffer[0];
        tx_queue_send(&mqtt_queue, &message_sent, TX_NO_WAIT);
        printf("Topic: %s, Message: %s\r\n", topic_buffer, message_buffer);

        // Any command on the incoming topic triggers an immediate telemetry publish.
        tx_event_flags_set(&mqtt_app_flag, MQTT_MESSAGE_READY, TX_OR);
    }
}

static VOID client_notify_func(NXD_MQTT_CLIENT *client_ptr, UINT number_of_messages)
{
    NX_PARAMETER_NOT_USED(client_ptr);
    NX_PARAMETER_NOT_USED(number_of_messages);
    tx_event_flags_set(&mqtt_app_flag, MQTT_RECEIVE_EVENT, TX_OR);
    return;
}

/* Reconnect timing: retry after 1 s, doubling up to 10 s, until the broker is back. */
#define MQTT_CONNECT_TIMEOUT       (10 * TX_TIMER_TICKS_PER_SECOND)
#define MQTT_RECONNECT_DELAY_MIN_S 1
#define MQTT_RECONNECT_DELAY_MAX_S 10

static ULONG error_count;

/* Opens one MQTT session: Last Will, connect, "online" status, subscriptions.
 * Returns NXD_MQTT_SUCCESS only if everything is in place; on failure no session is left open. */
static UINT mqtt_open_session(NXD_ADDRESS *server_ip){
    UINT status;

    /* Last Will: the broker publishes "offline" (QoS 1, retained) if this client disappears without a
     * clean disconnect, so the rest of the system can tell "sensor offline" from a stale value.
     * The client forgets the will when a connection ends, so it is set again before every connect. */
    status = nxd_mqtt_client_will_message_set(&mqtt_client,
                                              (UCHAR *)MQTT_STATUS_TOPIC, STRLEN(MQTT_STATUS_TOPIC),
                                              (UCHAR *)MQTT_STATUS_OFFLINE, STRLEN(MQTT_STATUS_OFFLINE),
                                              1, QOS1);
    if (status != NXD_MQTT_SUCCESS){
        printf("MQTT will message setup failed with code: %d\r\n", status);
    }

    /* clean_session = 1: no persistent session. With 0 the broker queues QoS 1 messages (display commands)
     * while the board is away and replays them on every connect, so one oversized message would crash the
     * connection again after each reboot. Retained messages are still delivered on subscribe. */
    status = nxd_mqtt_client_connect(&mqtt_client, server_ip, NXD_MQTT_PORT,
                                     MQTT_KEEP_ALIVE_TIMER, 1, MQTT_CONNECT_TIMEOUT);
    if (status != NXD_MQTT_SUCCESS){
        printf("MQTT connect failed with code: %d\r\n", status);
        return status;
    }
    printf("MQTT Client connected.\r\n");

    /* Replace the retained "offline" with "online" (QoS 1, retained). */
    status = nxd_mqtt_client_publish(&mqtt_client, MQTT_STATUS_TOPIC, STRLEN(MQTT_STATUS_TOPIC),
                                     (CHAR *)MQTT_STATUS_ONLINE, STRLEN(MQTT_STATUS_ONLINE), 1, QOS1, NX_WAIT_FOREVER);
    if (status != NXD_MQTT_SUCCESS){
        printf("Status publish failed with code: %d\r\n", status);
    }

    /* On-demand request topic. */
    status = nxd_mqtt_client_subscribe(&mqtt_client, MQTT_SUBSCRIBE_TOPIC, STRLEN(MQTT_SUBSCRIBE_TOPIC), QOS0);
    if (status != NXD_MQTT_SUCCESS){
        printf("MQTT subscribe failed with code: %d\r\n", status);
        nxd_mqtt_client_disconnect(&mqtt_client);
        return status;
    }
    printf("Subscribed to topic %s.\r\n", MQTT_SUBSCRIBE_TOPIC);

    /* Guardian state for the OLED: QoS 1, the broker re-delivers the retained last state on subscribe. */
    status = nxd_mqtt_client_subscribe(&mqtt_client, MQTT_DISPLAY_TOPIC, STRLEN(MQTT_DISPLAY_TOPIC), QOS1);
    if (status != NXD_MQTT_SUCCESS){
        printf("MQTT subscribe failed with code: %d\r\n", status);
        nxd_mqtt_client_disconnect(&mqtt_client);
        return status;
    }
    printf("Subscribed to topic %s.\r\n", MQTT_DISPLAY_TOPIC);

    return NXD_MQTT_SUCCESS;
}

static void mqtt_thread_work(NX_IP *ip_ptr, NX_PACKET_POOL *pool_ptr){
    UINT status;
    NXD_ADDRESS server_ip;
    ULONG events;
    UINT connected = 0;
    ULONG retry_delay_s = MQTT_RECONNECT_DELAY_MIN_S;

    /* Create an event flag for this demo. Before the client: its disconnect notify signals it. */
    status = tx_event_flags_create(&mqtt_app_flag, "MQTT event");
    if (status)
        error_count++;

    printf("Creating MQTT client\r\n");
    /* Create MQTT client instance. */
    status = nxd_mqtt_client_create(&mqtt_client, MQTT_CLIENT_NAME, MQTT_CLIENT_ID, STRLEN(MQTT_CLIENT_ID),
                                    ip_ptr, pool_ptr, (VOID *)mqtt_client_stack, sizeof(mqtt_client_stack),
                                    MQTT_THREAD_PRIORTY, NX_NULL, 0);

    if (status){
        printf("Error in creating MQTT client: 0x%02x\n", status);
        error_count++;
    }

    printf(" MQTT client created\r\n");

    /* Register the disconnect notification function. */
    nxd_mqtt_client_disconnect_notify_set(&mqtt_client, client_disconnect_func);

    /* Set the receive notify function. */
    status = nxd_mqtt_client_receive_notify_set(&mqtt_client, client_notify_func);
    if (status != NXD_MQTT_SUCCESS){
                printf("MQTT receive notify setup failed with code: %d\r\n", status);
    }
    else{
        printf("MQTT Receive notify function set.\r\n");
    }

    server_ip.nxd_ip_version = 4;
    server_ip.nxd_ip_address.v4 = MQTT_LOCAL_BROKER_IP;

    while (1){
        if (!connected){
            if (server_ip.nxd_ip_address.v4 == 0){
                printf("MQTT_LOCAL_BROKER_IP is not set: define it in cloud_config_local.h.\r\n");
                tx_thread_sleep(MQTT_RECONNECT_DELAY_MAX_S * TX_TIMER_TICKS_PER_SECOND);
                continue;
            }
            if (mqtt_open_session(&server_ip) != NXD_MQTT_SUCCESS){
                printf("MQTT retry in %u s.\r\n", (unsigned)retry_delay_s);
                tx_thread_sleep(retry_delay_s * TX_TIMER_TICKS_PER_SECOND);
                retry_delay_s = (retry_delay_s * 2 > MQTT_RECONNECT_DELAY_MAX_S) ? MQTT_RECONNECT_DELAY_MAX_S : retry_delay_s * 2;
                continue;
            }

            connected = 1;
            retry_delay_s = MQTT_RECONNECT_DELAY_MIN_S;
            /* A disconnect event left over from the session that just ended must not end this one. */
            tx_event_flags_set(&mqtt_app_flag, ~MQTT_DISCONNECT_EVENT, TX_AND);
            printf("Waiting for messages\r\n");
        }

        tx_event_flags_get(&mqtt_app_flag, MQTT_ALL_EVENTS, TX_OR_CLEAR, &events, TX_WAIT_FOREVER);

        if (events & MQTT_DISCONNECT_EVENT){
            printf("Lost the broker connection, reconnecting.\r\n");
            connected = 0;
            continue;
        }
        if (events & MQTT_RECEIVE_EVENT){
            receive_message();
        }
        if (events & MQTT_MESSAGE_READY){
            if (send_message() == NXD_MQTT_NOT_CONNECTED){
                /* Safety net in case the disconnect notification was missed. The client is already idle. */
                printf("Publish found no connection, reconnecting.\r\n");
                connected = 0;
            }
        }
    }
}

void mqtt_thread_entry(ULONG parameter){

    UINT status;

    printf("Starting Eclipse ThreadX MQTT thread\r\n\r\n");

    // Initialize the network
    if ((status = wwd_network_init(WIFI_SSID, WIFI_PASSWORD, WIFI_MODE))){
        printf("ERROR: Failed to initialize the network (0x%08x)\r\n", status);
    }

    wwd_network_connect();

    mqtt_thread_work(&nx_ip, nx_pool);
}
