# Basic LCD display support
#
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2018  Aleph Objects, Inc <marcio@alephobjects.com>
# Copyright (C) 2018  Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import hd44780, st7920, uc1701, menu, status

LCD_chips = {
    'st7920': st7920.ST7920, 'hd44780': hd44780.HD44780,
    'uc1701': uc1701.UC1701, 'ssd1306': uc1701.SSD1306, 'sh1106': uc1701.SH1106,
}

class PrinterLCD:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.lcd_chip = config.getchoice('lcd_type', LCD_chips)(config)
        self.lcd_type = config.get('lcd_type')
        # menu
        self.menu = menu.MenuManager(config, self.lcd_chip)
        # display status helper
        self.get_status = status.DisplayStatus(config).get_status
        # printer objects
        self.gcode = self.printer.lookup_object('gcode')
        self.toolhead = self.sdcard = None
        self.fan = self.extruder = self.extruder1 = self.heater_bed = None
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        # screen updating
        self.screen_update_timer = self.reactor.register_timer(
            self.screen_update_event)
    # Initialization
    def handle_ready(self):
        self.lcd_chip.init()
        # Load printer objects
        self.toolhead = self.printer.lookup_object('toolhead')
        self.sdcard = self.printer.lookup_object('virtual_sdcard', None)
        self.fan = self.printer.lookup_object('fan', None)
        self.extruder = self.printer.lookup_object('extruder', None)
        self.extruder1 = self.printer.lookup_object('extruder1', None)
        self.heater_bed = self.printer.lookup_object('heater_bed', None)
        # Start screen update timer
        self.reactor.update_timer(self.screen_update_timer, self.reactor.NOW)
    # Get menu instance
    def get_menu(self):
        return self.menu
    # Graphics drawing
    def animate_glyphs(self, eventtime, x, y, glyph_name, do_animate):
        frame = do_animate and int(eventtime) & 1
        self.lcd_chip.write_glyph(x, y, glyph_name + str(frame + 1))
    def draw_progress_bar(self, x, y, width, value):
        value = int(value * 100.)
        data = [0x00] * width
        char_pcnt = int(100/width)
        for i in range(width):
            if (i+1)*char_pcnt <= value:
                # Draw completely filled bytes
                data[i] |= 0xFF
            elif (i*char_pcnt) < value:
                # Draw partially filled bytes
                data[i] |= (-1 << 8-((value % char_pcnt)*8/char_pcnt)) & 0xff
        data[0] |= 0x80
        data[-1] |= 0x01
        self.lcd_chip.write_graphics(x, y, 0, [0xff]*width)
        for i in range(1, 15):
            self.lcd_chip.write_graphics(x, y, i, data)
        self.lcd_chip.write_graphics(x, y, 15, [0xff]*width)
    # Screen updating
    def screen_update_event(self, eventtime):
        # update menu component
        ret = self.menu.screen_update_event(eventtime)
        if ret:
            return ret
        # update all else
        self.lcd_chip.clear()
        if self.lcd_type == 'hd44780':
            self.screen_update_hd44780(eventtime)
        else:
            self.screen_update_128x64(eventtime)
        self.lcd_chip.flush()
        return eventtime + .500
    def screen_update_hd44780(self, eventtime):
        lcd_chip = self.lcd_chip
        # Heaters
        if self.extruder is not None:
            info = self.extruder.get_heater().get_status(eventtime)
            lcd_chip.write_glyph(0, 0, 'extruder')
            self.draw_heater(1, 0, info)
        if self.extruder1 is not None:
            info = self.extruder1.get_heater().get_status(eventtime)
            lcd_chip.write_glyph(0, 1, 'extruder')
            self.draw_heater(1, 1, info)
        if self.heater_bed is not None:
            info = self.heater_bed.get_status(eventtime)
            lcd_chip.write_glyph(10, 0, 'bed')
            self.draw_heater(11, 0, info)
        # Fan speed
        if self.fan is not None:
            info = self.fan.get_status(eventtime)
            lcd_chip.write_text(10, 1, "Fan")
            self.draw_percent(14, 1, 4, info['speed'])
        # G-Code speed factor
        gcode_info = self.gcode.get_status(eventtime)
        lcd_chip.write_glyph(0, 2, 'feedrate')
        self.draw_percent(1, 2, 4, gcode_info['speed_factor'])
        # Print progress
        if (self.sdcard is not None
            and self.sdcard.get_status(eventtime)['progress']):
            lcd_chip.write_glyph(8, 2, 'sd')
        else:
            lcd_chip.write_glyph(8, 2, 'usb')
        display_info = self.get_status(eventtime)
        progress = display_info['progress']
        self.draw_percent(9, 2, 4, progress)
        lcd_chip.write_glyph(14, 2, 'clock')
        toolhead_info = self.toolhead.get_status(eventtime)
        self.draw_time(15, 2, toolhead_info['printing_time'])
        self.draw_status(0, 3, display_info, gcode_info, toolhead_info)
    def screen_update_128x64(self, eventtime):
        # Heaters
        if self.extruder is not None:
            info = self.extruder.get_heater().get_status(eventtime)
            self.lcd_chip.write_glyph(0, 0, 'extruder')
            self.draw_heater(2, 0, info)
        extruder_count = 1
        if self.extruder1 is not None:
            info = self.extruder1.get_heater().get_status(eventtime)
            self.lcd_chip.write_glyph(0, 1, 'extruder')
            self.draw_heater(2, 1, info)
            extruder_count = 2
        if self.heater_bed is not None:
            info = self.heater_bed.get_status(eventtime)
            if info['target']:
                self.animate_glyphs(eventtime, 0, extruder_count,
                                    'bed_heat', True)
            else:
                self.lcd_chip.write_glyph(0, extruder_count, 'bed')
            self.draw_heater(2, extruder_count, info)
        # Fan speed
        if self.fan is not None:
            info = self.fan.get_status(eventtime)
            self.animate_glyphs(eventtime, 10, 0, 'fan', info['speed'] != 0.)
            self.draw_percent(12, 0, 4, info['speed'], '>')
        # SD card print progress
        display_info = self.get_status(eventtime)
        progress = display_info['progress']
        if progress is not None:
            if extruder_count == 1:
                x, y, width = 0, 2, 10
            else:
                x, y, width = 10, 1, 6
            self.draw_percent(x, y, width, progress, '^')
            self.draw_progress_bar(x, y, width, progress)
        # G-Code speed factor
        gcode_info = self.gcode.get_status(eventtime)
        if extruder_count == 1:
            self.lcd_chip.write_glyph(10, 1, 'feedrate')
            self.draw_percent(12, 1, 4, gcode_info['speed_factor'], '>')
        # Printing time and status
        toolhead_info = self.toolhead.get_status(eventtime)
        printing_time = toolhead_info['printing_time']
        remaining_time = None
        if progress is not None and progress > 0:
            remaining_time = int(printing_time / progress) - printing_time
        # switch mode every 6s
        if remaining_time is not None and int(eventtime) % 12 < 6:
            self.lcd_chip.write_text(10, 2, "-")
            self.draw_time(11, 2, remaining_time)
        else:
            offset = 1 if printing_time < 100 * 60 * 60 else 0
            self.draw_time(10 + offset, 2, printing_time)
        self.draw_status(0, 3, display_info, gcode_info, toolhead_info)
    # Screen update helpers
    def draw_text(self, x, y, mixed_text):
        pos = x
        for i, text in enumerate(mixed_text.split('~')):
            if i & 1 == 0:
                # write text
                self.lcd_chip.write_text(pos, y, text)
                pos += len(text)
            else:
                # write glyph
                pos += self.lcd_chip.write_glyph(pos, y, text)
    def draw_heater(self, x, y, info):
        temperature, target = info['temperature'], info['target']
        if target and abs(temperature - target) > 2.:
            self.draw_text(x, y, "%3.0f~right_arrow~%.0f~degrees~" % (
                temperature, target))
        else:
            self.draw_text(x, y, "%3.0f~degrees~" % (temperature,))
    def draw_percent(self, x, y, width, value, align='^'):
        self.lcd_chip.write_text(x, y, '{:{}{}.0%}'.format(value, align, width))
    def draw_time(self, x, y, seconds):
        seconds = int(seconds)
        self.lcd_chip.write_text(x, y, "%02d:%02d" % (
            seconds // (60 * 60), (seconds // 60) % 60))
    def draw_status(self, x, y, display_info, gcode_info, toolhead_info):
        if display_info['message']:
            self.lcd_chip.write_text(x, y, display_info['message'])
            return
        status = toolhead_info['status']
        if status == 'Printing' or gcode_info['busy']:
            pos = self.toolhead.get_position()
            status = "X%-4.0fY%-4.0fZ%-5.2f" % (pos[0], pos[1], pos[2])
        self.lcd_chip.write_text(x, y, status)

def load_config(config):
    return PrinterLCD(config)
