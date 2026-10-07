/*
 *  Display command from the RoM guardian (rom/actuator/display/cmd, see common/contracts.py):
 *    {"state":"CRITICAL","temp_c":29.07,"reason":"too hot","seq":845,"ts_ms":1791306322545}
 *
 *  SPDX-License-Identifier: MIT
 */
#ifndef _DISPLAY_CMD_H
#define _DISPLAY_CMD_H

#include "tx_api.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define DISPLAY_STATE_MAX  16
#define DISPLAY_REASON_MAX 32

/* No command for this long (or one stamped this long ago) means the guardian is gone. The guardian re-sends
 * every second, so this also catches an old retained command delivered right after connecting. */
#define DISPLAY_STALE_MS 5000

typedef struct
{
    char     state[DISPLAY_STATE_MAX];
    char     reason[DISPLAY_REASON_MAX];
    bool     has_temp; /* temp_c may be null */
    float    temp_c;
    uint32_t seq;
    uint64_t ts_ms; /* 0 if absent */
} display_cmd_t;

/* Parses and validates one command. Returns false for anything that is not a contract-valid command
 * (bad JSON, unknown state, nested values, ...); `out` is only written on success. Never reads past length. */
bool display_cmd_parse(const char* json, size_t length, display_cmd_t* out);

/* MQTT thread stores the latest valid command; the OLED thread loads it. */
void display_cmd_store(const display_cmd_t* cmd);

/* Returns false if no command was ever stored. `stale` tells whether the guardian stopped talking. */
bool display_cmd_load(display_cmd_t* cmd, bool* stale);

#endif /* _DISPLAY_CMD_H */
