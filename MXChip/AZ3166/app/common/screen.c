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

#include "screen.h"

#include "ssd1306.h"

void screen_print(char* str, LINE_NUM line)
{
    ssd1306_Fill(Black);
    ssd1306_SetCursor(2, line);
    ssd1306_WriteString(str, Font_11x18, White);
    ssd1306_UpdateScreen();
}

// Fits up to 7 tiny lines (6x8 font, 9px pitch) on the 128x64 OLED.
void screen_print_small(const char* lines[], unsigned int line_count)
{
    ssd1306_Fill(Black);

    uint8_t y = 0;
    for (unsigned int i = 0; i < line_count && (y + 8) <= SSD1306_HEIGHT; ++i)
    {
        ssd1306_SetCursor(0, y);
        ssd1306_WriteString((char*)lines[i], Font_6x8, White);
        y += 9;
    }

    ssd1306_UpdateScreen();
}

void screen_printn(const char* str, unsigned int str_length, LINE_NUM line)
{
    ssd1306_Fill(Black);
    ssd1306_SetCursor(2, line);

    for (unsigned int i = 0; i < str_length; ++i)
    {
        if (ssd1306_WriteChar(str[i], Font_11x18, White) != str[i])
        {
            return;
        }
    }

    ssd1306_UpdateScreen();
}