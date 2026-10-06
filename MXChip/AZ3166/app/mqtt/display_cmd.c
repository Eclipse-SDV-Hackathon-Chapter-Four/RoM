/*
 *  Display command from the RoM guardian. See display_cmd.h.
 *
 *  SPDX-License-Identifier: MIT
 */
#include "display_cmd.h"
#include "jsmn.h"
#include "sntp_client.h"
#include <string.h>

#define MAX_TOKENS   24
#define EPOCH_MS_MIN 1000000000000ULL

/* Keep in sync with STATES in common/contracts.py. */
static const char* const KNOWN_STATES[] = {"CLEAR", "MONITORING", "WARNING", "CRITICAL", "SENSOR_FAULT"};

static display_cmd_t current_cmd;
static bool          have_cmd;
static ULONG         rx_ticks;

static bool text_equals(const char* text, int length, const char* expected)
{
    size_t n = strlen(expected);
    return length >= 0 && (size_t)length == n && memcmp(text, expected, n) == 0;
}

static bool known_state(const char* text, int length)
{
    for (size_t i = 0; i < sizeof(KNOWN_STATES) / sizeof(KNOWN_STATES[0]); ++i)
    {
        if (text_equals(text, length, KNOWN_STATES[i]))
        {
            return true;
        }
    }
    return false;
}

static bool parse_u64(const char* text, int length, uint64_t* out)
{
    if (length <= 0 || length > 20)
    {
        return false;
    }

    uint64_t value = 0;
    for (int i = 0; i < length; ++i)
    {
        if (text[i] < '0' || text[i] > '9')
        {
            return false;
        }
        value = value * 10u + (uint64_t)(text[i] - '0');
    }
    *out = value;
    return true;
}

/* [-]digits[.digits] only. No exponent, no NaN/Infinity: the caller then just shows no temperature. */
static bool parse_temp(const char* text, int length, float* out)
{
    int    i          = 0;
    bool   negative   = false;
    int    int_digits = 0;
    double value      = 0.0;
    double scale      = 0.1;

    if (i < length && text[i] == '-')
    {
        negative = true;
        ++i;
    }
    while (i < length && text[i] >= '0' && text[i] <= '9')
    {
        value = value * 10.0 + (double)(text[i] - '0');
        ++i;
        ++int_digits;
    }
    if (i < length && text[i] == '.')
    {
        ++i;
        while (i < length && text[i] >= '0' && text[i] <= '9')
        {
            value += (double)(text[i] - '0') * scale;
            scale /= 10.0;
            ++i;
        }
    }
    if (i != length || int_digits == 0)
    {
        return false;
    }

    *out = (float)(negative ? -value : value);
    return true;
}

/* Truncating copy that only lets printable ASCII through (the OLED font has nothing else). */
static void copy_text(char* dst, size_t dst_size, const char* src, int length)
{
    size_t n = ((size_t)length < dst_size - 1) ? (size_t)length : dst_size - 1;
    for (size_t i = 0; i < n; ++i)
    {
        unsigned char c = (unsigned char)src[i];
        dst[i]          = (c >= 0x20 && c < 0x7F) ? (char)c : '?';
    }
    dst[n] = '\0';
}

bool display_cmd_parse(const char* json, size_t length, display_cmd_t* out)
{
    jsmn_parser   parser;
    jsmntok_t     tokens[MAX_TOKENS];
    display_cmd_t cmd;
    bool          have_state = false;

    memset(&cmd, 0, sizeof(cmd));
    jsmn_init(&parser);
    int count = jsmn_parse(&parser, json, (unsigned int)length, tokens, MAX_TOKENS);
    if (count < 1 || tokens[0].type != JSMN_OBJECT)
    {
        return false;
    }

    /* The contract is a flat object: key, value, key, value, ... Anything nested is not ours. */
    for (int i = 1; i + 1 < count; i += 2)
    {
        const jsmntok_t* key = &tokens[i];
        const jsmntok_t* val = &tokens[i + 1];
        if (key->type != JSMN_STRING || (val->type != JSMN_STRING && val->type != JSMN_PRIMITIVE))
        {
            return false;
        }

        const char* name  = json + key->start;
        int         nlen  = key->end - key->start;
        const char* value = json + val->start;
        int         vlen  = val->end - val->start;
        uint64_t    number;

        if (text_equals(name, nlen, "state"))
        {
            if (val->type != JSMN_STRING || !known_state(value, vlen))
            {
                return false;
            }
            copy_text(cmd.state, sizeof(cmd.state), value, vlen);
            have_state = true;
        }
        else if (text_equals(name, nlen, "temp_c"))
        {
            cmd.has_temp = (val->type == JSMN_PRIMITIVE) && parse_temp(value, vlen, &cmd.temp_c);
        }
        else if (text_equals(name, nlen, "reason"))
        {
            if (val->type == JSMN_STRING)
            {
                copy_text(cmd.reason, sizeof(cmd.reason), value, vlen);
            }
        }
        else if (text_equals(name, nlen, "seq"))
        {
            if (val->type == JSMN_PRIMITIVE && parse_u64(value, vlen, &number))
            {
                cmd.seq = (uint32_t)number;
            }
        }
        else if (text_equals(name, nlen, "ts_ms"))
        {
            if (val->type == JSMN_PRIMITIVE && parse_u64(value, vlen, &number))
            {
                cmd.ts_ms = number;
            }
        }
        /* Unknown keys are ignored. */
    }

    if (!have_state)
    {
        return false;
    }

    *out = cmd;
    return true;
}

void display_cmd_store(const display_cmd_t* cmd)
{
    TX_INTERRUPT_SAVE_AREA

    TX_DISABLE
    current_cmd = *cmd;
    rx_ticks    = tx_time_get();
    have_cmd    = true;
    TX_RESTORE
}

bool display_cmd_load(display_cmd_t* cmd, bool* stale)
{
    ULONG ticks;
    bool  have;

    TX_INTERRUPT_SAVE_AREA

    TX_DISABLE
    have   = have_cmd;
    *cmd   = current_cmd;
    ticks  = tx_time_get() - rx_ticks;
    TX_RESTORE

    if (!have)
    {
        return false;
    }

    /* Silence from the guardian... */
    *stale = ticks > (ULONG)((DISPLAY_STALE_MS * (uint64_t)TX_TIMER_TICKS_PER_SECOND) / 1000u);

    /* ...or a command that was already old when it arrived (retained message from an earlier run).
     * Only comparable when both clocks are epoch time (board synced over SNTP). */
    if (!*stale && cmd->ts_ms >= EPOCH_MS_MIN)
    {
        uint64_t now_ms = sntp_time_ms_get();
        if (now_ms >= EPOCH_MS_MIN && now_ms > cmd->ts_ms && (now_ms - cmd->ts_ms) > DISPLAY_STALE_MS)
        {
            *stale = true;
        }
    }

    return true;
}
