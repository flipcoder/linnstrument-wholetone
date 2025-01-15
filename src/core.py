#!/usr/bin/python3
# from tkinter import *
from collections import OrderedDict
from configparser import ConfigParser
import os, sys, glm, copy, binascii, struct, math, traceback, signal
import rtmidi2
from dataclasses import dataclass
from glm import ivec2, vec2, ivec3, vec3
import time

from src.util import *
from src.constants import *
from src.settings import Settings, DEFAULT_OPTIONS
from src.note import Note
from src.device import Device, DeviceSettings
from src.launchpad import Launchpad
from src.articulation import Articulation
# from src.gamepad import Gamepad

with open(os.devnull, "w") as devnull:
    # suppress pygame messages (to keep console output clean)
    stdout = sys.stdout
    sys.stdout = devnull
    import pygame, pygame.midi, pygame.gfxdraw

    sys.stdout = stdout
import pygame_gui

try:
    import launchpad_py as launchpad
except ImportError:
    try:
        import launchpad
    except ImportError:
        error("The project dependencies have changed! Run the requirements setup command again!")

try:
    import yaml
except ImportError:
    error("The project dependencies have changed! Run the requirements setup command again!")

# import mido

try:
    import musicpy as mp
except ImportError:
    error("The project dependencies have changed! Run the requirements setup command again!")

class Core:
    CORE = None
    
    def rotate_mode(self, notes: str, mode: int):
        """Rotates a mode string (see: scales.yaml strings with x and .)"""
        notes = copy.copy(notes)
        while mode:
            if notes[0] == 'x':
                notes = notes[1:] + notes[0]
            while notes[0] == '.':
                notes = notes[1:] + notes[0]
            mode -= 1
        return notes

    def prev_bank(self):
        return self.next_bank(-1)
    
    def next_bank(self, ofs=1):
        if not self.midi_out:
            return False
        self.bank = max(0, min(127, self.bank + ofs))
        msb = (self.bank >> 7) & 0x7f
        lsb = self.bank & 0x7f
        self.midi_out.send_cc(0, 0, msb)
        self.midi_out.send_cc(0, 32, lsb)
        print('Bank Select: ', self.bank)
        return True
    
    def prev_program(self):
        return self.next_program(-1)
    
    def next_program(self, ofs=1):
        if not self.midi_out:
            return False
        self.program = max(0, min(127, self.program + ofs))
        self.midi_write(self.midi_out, [0xc0, self.program], 0)
        print('Program Change:', self.program)
        return True

    def prev_mode(self, ofs=1):
        self.next_mode(-ofs)

    def next_mode(self, ofs=1):
        """Go to next mode according to offset (ofs), wrapping around if necessary"""
        self.set_mode((self.mode_index + ofs) % self.scale_notes.count('x'))
        self.dirty = self.dirty_lights = True

    def toggle_sharps_flats(self, ofs=1):
        if (self.use_sharps):
            self.use_sharps = False
            self.NOTES = NOTES_FLATS
        else:
            self.use_sharps = True
            self.NOTES = NOTES_SHARPS
        self.dirty = self.dirty_lights = True

    def prev_scale(self, ofs=1):
        self.next_scale(-ofs)

    def next_scale(self, ofs=1):
        """Goes to first mode of the next scale in the scale db (ofs=offset)"""
        self.scale_index = (self.scale_index + ofs) % len(self.scale_db)
        self.scale_name = self.scale_db[self.scale_index]['name']
        self.set_mode(0)
        self.dirty = self.dirty_lights = True
    
    def set_mode(self, mode: int):
        """Set mode by index (0-indexed)"""
        self.scale_notes = self.rotate_mode(self.scale_db[self.scale_index]['notes'], mode)
        self.mode_index = mode
        try:
            self.mode_name = self.scale_db[self.scale_index]['modes'][mode]
        except:
            self.mode_name = 'Mode ' + str(self.mode_index + 1)
        self.scale_root = mode

    def set_scale(self, scale: int, mode: int):
        """Set scale and mode by number, 0-indexed"""
        self.scale_index = scale
        self.scale_name = self.scale_db[scale]['name']
        self.set_mode(mode)
    
    def has_velocity_curve(self):
        """Does user have custom velocity curve from the config?"""
        return abs(self.velocity_curve_ - 1.0) > EPSILON

    def has_velocity_settings(self):
        """Does user have any velocity settings from the config?"""
        return (
            self.options.min_velocity > 0
            or self.options.max_velocity < 127
            or self.has_velocity_curve()
        )

    def velocity_curve(self, val):  # 0-1
        """Apply custom velocity curve from config, if available"""
        if self.has_velocity_curve():
            val = val**self.velocity_curve_
        return val

    def send_ls_cc(self, channel, cc, val):
        """Send CC to LinnStrument channel with value, if connected"""
        if not self.linn_out:
            return
        # msg = [0xb0 | channel, cc, val]
        self.linn_out.send_cc(channel, cc, val)
        # self.linn_out.send_messages(0xb0, [(channel, cc, val)])

    def send_all_notes_off(self):
        if not self.midi_out:
            return
        # for ch in range(0,15):
        ch = 0
        self.midi_write(self.midi_out, [0xb0 | ch, 120, 0], 0)
        self.midi_write(self.midi_out, [0xb0 | ch, 123, 0], 0)

    def ls_color(self, x, y, col):
        """Set LinnStrument pad color"""
        if self.linn_out:
            self.send_ls_cc(0, 20, x + 1)
            self.send_ls_cc(0, 21, self.board_h - y - 1)
            self.send_ls_cc(0, 22, col)

    def set_light(self, x, y, col, index=None, mark=False):  # col is [1,11], 0 resets
        """Set light to color `col` at x, y if in range and connected"""
        if y < 0 or y >= self.board_h:
            return
        if x < 0 or x >= self.board_w:
            return

        if not index:
            index = self.get_note_index(x, y, transpose=False)

        self.mark_lights[y][x] = mark
        
        self.ls_color(x, y, col)

        if index is not None:
            for lp in self.launchpads:
                if self.scale_notes[index] != '.':
                    if self.options.launchpad_colors:
                        lp_col = self.options.launchpad_colors[index]
                    else:
                        lp_col = self.options.colors[index] / 4
                else:
                    if self.options.launchpad_colors:
                        lp_col = 0
                    else:
                        lp_col = ivec3(0)
                if 0 <= x < 8 and 0 <= y < 8:
                    if not self.is_macro_button(x, y):
                        if self.options.launchpad_colors:
                            lp.out.LedCtrlXYByCode(x, y+1, lp_col)
                        else:
                            lp.out.LedCtrlXY(x, y+1, lp_col[0], lp_col[1], None if lp_col[2] == 0 else lp_col[2])
                    else:
                        if self.options.launchpad_colors:
                            lp.out.LedCtrlXYByCode(x, y+1, 3)
                        else:
                            lp.out.LedCtrlXY(x, y+1, 63, 63, 63)

    def reset_light(self, x, y, reset_red=True):
        """Reset the light at x, y"""
        note = self.get_note_index(x, y, transpose=False)
        
        if self.is_split():
            split_chan = self.channel_from_split(x, self.board_h - y - 1)
            if split_chan:
                light_col = self.options.split_lights[note]
                try:
                    light_col = light_col if self.scale_notes[note]!='.' else 7
                except IndexError:
                    light_col = 7
            else:
                light_col = self.options.lights[note]
                try:
                    light_col = light_col if self.scale_notes[note]!='.' else 7
                except IndexError:
                    light_col = 7
        else:
            light_col = self.options.lights[note]
            try:
                light_col = light_col if self.scale_notes[note]!='.' else 7
            except IndexError:
                light_col = 7

        self.set_light(x, y, light_col, note)
        self.mark_lights[y][x] = False

    def reset_launchpad_light(self, x, y, launchpad=None):
        """Reset the launchpad light at x, y"""
        note = self.get_note_index(x, 8-y-1, transpose=False)
        # if self.is_split():
        #     split_chan = self.channel_from_split(x, self.board_h - y - 1)
        #     if split_chan:
        #         light_col = self.options.split_lights[note]
        #     else:
        # light_col = self.options.lights[note]
        # else:
        #     light_col = self.options.lights[note]
        for lp in ([launchpad] if launchpad else self.launchpads):
            self.set_launchpad_light(x, y, note)

    def set_mark_light(self, x, y, state=True, launchpad=None):
        """Set launchpad light to touched color"""
        self.mark_lights[y][x] = state
        for lp in ([launchpad] if launchpad else self.launchpads):
            lp_col = self.options.mark_color
            if state:
                lp.out.LedCtrlXY(x, y, lp_col[0], lp_col[1], lp_col[2])

    # `color` below is an scale index (0, 1, 2...)
    def set_launchpad_light(self, x, y, color, launchpad=None):
        """Set launchpad light to color index"""
        if self.is_macro_button(x, 8 - y - 1):
            if self.options.launchpad_colors:
                col = 1
            else:
                col = glm.ivec3(63,63,63)
        else:
            if color != -1: # not mark
                if color is not None and self.scale_notes[color] != '.':
                    if self.options.launchpad_colors:
                        col = self.options.launchpad_colors[color]
                    else:
                        col = self.options.colors[color] / 4
                else:
                    if self.options.launchpad_colors:
                        col = 0
                    else:
                        col = glm.ivec3(0,0,0)
            else:
                if self.options.launchpad_colors:
                    col = 1
                else:
                    col = self.options.mark_color / 4

        for lp in ([launchpad] if launchpad else self.launchpads):
            if self.options.launchpad_colors:
                lp.out.LedCtrlXYByCode(x, 8-y, col)
            else:
                lp.out.LedCtrlXY(x, 8-y, col[0], col[1], col[2])

    def setup_lights(self):
        """Set all lights"""
        for y in range(self.board_h):
            for x in range(self.board_w):
                if self.mark_lights[y][x]:
                    self.set_mark_light(x, y, True)
                else:
                    self.reset_light(x, y)

    def reset_lights(self):
        """Reset all lights to device defaults"""
        for y in range(self.board_h):
            for x in range(self.board_w):
                self.set_light(x, y, 0)

    # def get_octave(self, x, y):
    #     try:
    #         return self.octaves[y - self.board_h + self.flipped][x] + self.octave
    #     except IndexError:
    #         pass

    def xy_to_midi(self, x, y, transpose=True):
        """x, y coordinate to midi note based on layout (this can be improved)"""
        y = self.board_h - y - 1
        column_offset = self.options.column_offset
        row_offset = self.options.row_offset
        xx = x + self.options.base_offset
        r = row_offset * y + (column_offset * (xx + self.position.x))
        r += 24
        if self.flipped:
            r += 7
        r += self.tonic if transpose else 0
        # print(x, y, r)
        return r

    def get_note_index(self, x, y, transpose=True):
        """Get the note index (0-11) for a given x, y"""
        y += self.flipped
        x += self.position.x
        column_offset = self.options.column_offset
        row_offset = self.options.row_offset
        y = self.board_h - y - 1
        x += self.options.base_offset
        tr = self.tonic if transpose else 0
        return (row_offset * y + column_offset * x + tr) % len(self.NOTES)
        # ofs = (self.board_h - y) // 2 + BASE_OFFSET
        # step = 2 if WHOLETONE else 1
        # tr = self.tonic if transpose else 0
        # if y % 2 == 1:
        #     return ((x - ofs) * step - tr) % len(NOTES)
        # else:
        #     return ((x - ofs) * step + 7 - tr) % len(NOTES)

    def get_note(self, x, y, transpose=True):
        """Get note name for x, y"""
        return self.NOTES[self.get_note_index(x, y, transpose=transpose)]

    def get_color(self, x, y):
        """Get color for x, y"""
        # return NOTE_COLORS[get_note_index(x, y)]
        note = self.get_note_index(x, y, transpose=False)
        # note = (note - self.tonic) % 12
        # if self.is_split():
        #     split_chan = self.channel_from_split(x, self.board_h - y - 1)
        #     if split_chan:
        #         light_col = self.options.split_lights[note]
        #         try:
        #             light_col = light_col if self.scale_notes[note]!='.' else 7
        #         except IndexError:
        #             light_col = 7
        #     else:
        #         light_col = self.options.lights[note]
        #         try:
        #             light_col = light_col if self.scale_notes[note]!='.' else 7
        #         except IndexError:
        #             light_col = 7

        # else:
        #     light_col = self.options.lights[note]
        #     try:
        #         light_col = light_col if self.scale_notes[note]!='.' else 7
        #     except IndexError:
        #         light_col = 7

        if self.scale_notes[note] != '.':
            if self.channel_from_split(x, self.board_h - y - 1):
                return self.options.split_colors[note]
            else:
                return self.options.colors[note]
        else:
            return None

    def mouse_held(self):
        """Is mouse button is being held down?"""
        return self.mouse_midi != -1

    # layout button x, y and velocity
    def mouse_pos_to_press(self, x, y):
        """Translate board space x, y position to grid coordinate x, y with velocity"""
        vel = y % int(self.button_sz)
        x /= int(self.button_sz)
        y /= int(self.button_sz)

        vel = vel / int(self.button_sz)
        
        vel = 1 - vel
        
        vel *= 127
        vel = clamp(0, 127, int(vel))

        x, y = int(x), int(y)
        return (x, y, vel)

    def mouse_press(self, x, y, state=True, hold=False, hover=False):
        """Do mouse press at x, y"""
        if y < 0:
            return

        if hover:
            btn = pygame.mouse.get_pressed(3)[0]
            if not btn:
                return

        # if we're not intending to hold the note, we release the previous primary note
        if not hover:
            if self.mouse_held():
                self.mouse_release()

        x, y, vel = self.mouse_pos_to_press(x, y)

        if hover and self.mouse_midi_vel is not None:
            # if hovering, get velocity of last click
            vel = self.mouse_midi_vel
        if not hover and self.mouse_midi_vel is None:
            self.mouse_midi_vel = vel # store velocity for initial click

        # vel = y % int(self.button_sz)
        # x /= int(self.button_sz)
        # y /= int(self.button_sz)

        # vel = vel / int(self.button_sz)
        # vel = 1 - vel
        # vel *= 127
        # vel = clamp(0, 127, int(vel))

        # x, y = int(x), int(y)
        v = ivec2(x, y)

        self.mark_xy(x, y, state)
        midinote = self.xy_to_midi(v.x, v.y)
        if hover:
            if self.mouse_midi == midinote:
                return
            else:
                self.mouse_release()
        if not hold:
            self.mouse_mark = v
            self.mouse_midi = midinote
            self.mouse_midi_vel = vel
        
        split_chan = self.channel_from_split(x, self.board_h - y - 1)
        
        data = [(0x90 if state else 0x80), midinote, vel]
        if split_chan:
            self.midi_write(self.split_out, data, 0)
        else:
            self.midi_write(self.midi_out, data, 0)

    def mouse_hold(self, x, y):
        """Do mouse hold at x, y"""
        return self.mouse_press(x, y, True, hold=True)

    def mouse_release(self, x=None, y=None):
        """Do mouse release at x, y"""
        # x and y provided? it's a specific coordinate
        if x is not None and y is not None:
            return self.mouse_press(x, y, False)
        # x and y not provided? it uses the primary mouse coordinate
        if self.mouse_midi != -1:
            self.mark_xy(self.mouse_mark.x, self.mouse_mark.y, False)
            data = [0x80, self.mouse_midi, 127]
            split_chan = self.channel_from_split(self.mouse_mark.x, self.board_h - self.mouse_mark.y - 1)
            if split_chan:
                self.midi_write(self.split_out, data, 0)
            else:
                self.midi_write(self.midi_out, data, 0)
            
            self.mouse_midi = -1

    def mouse_hover(self, x, y):
        """Do mouse hover at x, y"""
        self.mouse_press(x, y, hover=True)

    # Given an x,y position, find the octave
    #  (used to initialize octaves 2D array)
    def get_octave(self, x, y):
        """Get octave for x, y"""
        y = self.board_h - y - 1
        octave = int(x + 4 + self.position.x + y * 2.5) // 6
        return octave

    def held_note_count(self):
        """How many held notes?"""
        count = 0
        for n in self.notes:
            if n is not None and n.location:
                count += 1
        return count

    def init_board(self):
        """Initialize board"""
        # self.octaves = [
        #     # 200 size ---------------------------------------------------------------v
        #     # 128 size ------------------------------------v
        #     [3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 7, 7, 7, 7],
        #     [3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 7, 7],
        #     [2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 6, 6, 6, 6, 6],
        #     [2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5, 6, 6, 6],
        #     [1, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 5],
        #     [1, 1, 1, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5],
        #     [1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 5],
        #     [0, 0, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4]
        # ]
        # generate grid of octaves like above
        # self.octaves = []
        # for y in range(self.board_h + 1):  # 1 = flipping
        #     self.octaves.append([])
        #     line = []
        #     for x in range(self.max_width):
        #         octave = self.get_octave(x, y)
        #         self.octaves[y].append(octave)
        #         line.append(octave)
            # print(line)

        self.notes = [None] * 16  # polyphony
        for i, note in enumerate(self.notes):
            self.notes[i] = Note()

        # These are midi numbers, not indices, so they only have to be 127
        self.left_chord_notes = [False] * 127
        self.chord_notes = [False] * 127
        self.note_set = set()

    def midi_write(self, dev, msg, ts=0):
        """Write MIDI message `msg` to device `dev`"""
        # if type(dev) in (list,tuple):
        #     for d in dev:
        #         self.midi_write(d, msg, ts)
        #     return
        if dev:
            dev.send_raw(*msg)

    def next_free_note(self):
        """Get the next note available in the polyphony array"""
        for note in self.notes:
            if note.location is None:
                return note
        return None

    def is_mpe(self):
        return self.options.one_channel == 0

    def note_on(self, data, timestamp, width=None, curve=True, mpe=None, octave=0, transpose=0, force_channel=None):
        # if mpe is None:
        #     mpe = self.options.mpe
        d0 = data[0]
        # print(data)
        ch = d0 & 0x0F
        msg = (data[0] & 0xF0) >> 4
        aftertouch = (msg == 10)
        
        if force_channel:
            data[0] = (d0 & 0xF0) + (force_channel-1)
        elif not self.is_mpe():
            data[0] = (d0 & 0xF0) + (self.options.one_channel-1)
        
        row = None
        col = None

        within_hardware_split = False
        if width is None:
            if self.options.hardware_split:
                # if self.board_w == 25: # 200
                left_width = self.split_point
                right_width = self.board_w - left_width
                # print('hardware splits', left_width, right_width)
                if ch >= 8:
                    width = right_width
                    within_hardware_split = True
                else:
                    width = left_width
                # else:
                #     left_width = 8
                #     right_width = 8
                #     if ch >= 8:
                #         width = right_width
                #         within_hardware_split = True
                #     else:
                #         width = left_width
            else:
                width = self.board_w
            # else: # 128
                # width = 8 if self.options.hardware_split else 16
        
        if self.options.debug:
            print("MIDI:", data)
            print("Message:", msg)
            print("Channel:", ch)
            print("---")

        row = data[1] // width
        col = data[1] % width
        col_full = col + (left_width if within_hardware_split else 0)
        # midinote = self.xy_to_midi(col, row)
        # y = self.board_h - row - 1
        column_offset = self.options.column_offset
        row_offset = self.options.row_offset
        y = row
        x = col
        midinote = row_offset * y + column_offset * x
        midinote += 32
        if self.flipped:
            midinote += 7
        if within_hardware_split:
            midinote += self.options.column_offset * left_width
        visual_midinote = midinote
        midinote += 12 * (octave + self.octave)
        midinote += self.options.column_offset * self.position.x
        midinote += transpose + self.tonic

        # print(x, y, midinote)
        # return

        # # if mpe:
        
        # col_full = col + (left_width if within_hardware_split else 0)
        # if within_hardware_split:
        #     data[1] += left_width
        # data[1] = col + 30 + 2.5 * row
        # data[1] *= 2
        # data[1] = int(data[1])
        # if within_hardware_split:
        #     data[1] += left_width * 2
        #     # print(data[1])
        # # else:
        # #     row = ch % 8
        # #     col = ch // 8
        # #     data[1] *= 2
        # #     try:
        # #         data[1] -= row * 5
        # #     except IndexError:
        # #         pass
        
        # data[1] += (self.octave + self.octave_base + octave) * 12
        # data[1] += transpose
        # data[1] += BASE_OFFSET
        # midinote = data[1] - 24 + self.position.x * 2
        col_full = x + (left_width if within_hardware_split else 0)
        
        # figure out if note is on left or right side
        side = self.channel_from_split(col_full, row, force=True)

        # if the note is on the right side, we shift by the current octave split
        if side == 1:
            octave_split = self.options.octave_split
            if octave_split != 0:
                midinote += 12 * octave_split

        # if we have a split set up, set the side found above to split_chan,
        #   otherwise everything should be in the same region
        if self.is_split():
            split_chan = side
        else:
            split_chan = 0

        data[1] = midinote
        
        if not aftertouch:
            self.mark(visual_midinote - 24, 1, only_row=row)
        # data[1] += self.out_octave * 12 + self.position.x * 2
        # if self.flipped:
        #     data[1] += 7
        
        # velocity (or pressure if aftertouch)
        vel = data[2] / 127
        if curve and not aftertouch:
            # apply curve
            if self.has_velocity_settings():
                vel = self.velocity_curve(data[2] / 127)
                data[2] = clamp(
                    self.options.min_velocity,
                    self.options.max_velocity,
                    int(vel * 127 + 0.5),
                )

        if aftertouch:
            # TODO: add aftertouch values into notes array
            #   This is not necessary yet
            pass
        else:
            # if self.options.mpe:
            note = self.notes[ch]
            # else:
            #     note = self.next_free_note()
            if note:
                if note.location is None:
                    note.location = ivec2(0)
                note.location.x = x
                note.location.y = y
                note.pressure = vel
                note.midinote = midinote
                note.split = split_chan

            # if self.options.jazz:
            #     if side == 0:
            #         self.left_chord_notes[data[1]] = True
                    # self.dirty_left_chord = True
        
            self.chord_notes[midinote] = True
            self.note_set.add(midinote)
            self.dirty_chord = True

        if self.is_split():
            if split_chan == 0:
                # self.midi_out.write([[data, ev[1]]]
                self.midi_write(self.midi_out, data, timestamp)
            else:
                self.midi_write(self.split_out, data, timestamp)
        else:
            # print(data[1]) # midi note number
            self.midi_write(self.midi_out, data, timestamp)

    def note_off(self, data, timestamp, width=None, mpe=None, octave=0, transpose=0, force_channel=None):
        # if mpe is None:
        #     mpe = self.options.mpe
        
        d0 = data[0]
        # print(data)
        ch = d0 & 0x0F
        msg = (data[0] & 0xF0) >> 4
        if force_channel:
            data[0] = (d0 & 0xF0) + (force_channel-1)
        elif not self.is_mpe():
            data[0] = (d0 & 0xF0) + (self.options.one_channel-1)
        row = None
        col = None

        # if width is None:
        #     if self.board_w == 25: # 200
        #         width = 11 if self.options.hardware_split else 25
        #     else: # 128
        #         width = 8 if self.options.hardware_split else 16
        # if width is None:
        #     left_width = 5
        #     right_width = 11
        #     width = left_width if ch < 8 else right_width
        
        within_hardware_split = False
        if width is None:
            if self.options.hardware_split:
                # if self.board_w == 25: # 200
                left_width = self.split_point
                right_width = self.board_w - left_width
                # print('hardware splits', left_width, right_width)
                if ch >= 8:
                    width = right_width
                    within_hardware_split = True
                else:
                    width = left_width
                # else:
                #     left_width = 8
                #     right_width = 8
                #     if ch >= 8:
                #         width = right_width
                #         within_hardware_split = True
                #     else:
                #         width = left_width
            else:
                width = self.board_w
        
        # # if not mpe:
        # #     row = ch % 8
        # #     col = ch // 8
        # # if mpe:
        #     # row and col within the current split
        #     # row = data[1] // width
        #     # col = data[1] % width
        #     # print(data[1])
        #     # # data[1] = data[1] % width + 30 + 2.5 * row
        #     # data[1] *= 2
        #     # data[1] = int(data[1])
        #     # if self.options.hardware_split and ch >= 8:
        #     #     data[1] += self.board_w
        # row = data[1] // width
        # col = data[1] % width
        # col_full = col + (left_width if within_hardware_split else 0)
        # if within_hardware_split:
        #     data[1] += left_width
        # data[1] = col + 30 + 2.5 * row
        # data[1] *= 2
        # data[1] = int(data[1])
        # if within_hardware_split:
        #     data[1] += left_width * 2
        # # else:
        # #     data[1] *= 2
        # #     try:
        # #         data[1] -= row * 5
        # #     except IndexError:
        # #         pass
        
        # data[1] += (self.octave + self.octave_base + octave) * 12
        # data[1] += BASE_OFFSET
        # data[1] += transpose
        # midinote = data[1] - 24 + self.position.x * 2

        row = data[1] // width
        col = data[1] % width
        # print('xy', col, row)
        # col_full = col + (left_width if within_hardware_split else 0)
        # midinote = self.xy_to_midi(col, row)
        # y = self.board_h - row - 1
        column_offset = self.options.column_offset
        row_offset = self.options.row_offset
        y = row
        x = col
        midinote = row_offset * y + column_offset * x
        midinote += 32
        if self.flipped:
            midinote += 7
        if within_hardware_split:
            midinote += self.options.column_offset * left_width
        visual_midinote = midinote
        midinote += 12 * (octave + self.octave)
        midinote += self.options.column_offset * self.position.x
        midinote += transpose + self.tonic
        # print('off', x, y, midinote)

        col_full = x + (left_width if within_hardware_split else 0)
        side = self.channel_from_split(col_full, y, force=True)

        # if the note is on the right side, we shift by the current octave split
        if side == 1:
            octave_split = self.options.octave_split
            if octave_split != 0:
                midinote += 12 * octave_split
        
        if self.is_split():
            split_chan = side
        else:
            split_chan = 0

        data[1] = midinote
        
        self.mark(visual_midinote - 24, 0, only_row=y)
        # data[1] += self.out_octave * 12 + self.position.x * 2
        # if self.flipped:
        #     data[1] += 7

        # if self.options.jazz:
        #     if side == 0:
        #         self.left_chord_notes[data[1]] = False
                # self.dirty_left_chord = True
        
        self.chord_notes[data[1]] = False
        try:
            self.note_set.remove(data[1])
        except KeyError:
            pass
        self.dirty_chord = True

        if self.is_split():
            if split_chan == 0:
                self.midi_write(self.midi_out, data, timestamp)
            else:
                self.midi_write(self.split_out, data, timestamp)
        else:
            self.midi_write(self.midi_out, data, timestamp)
        # print('note off: ', data)

    # def device_to_xy(self, data, force_channel=None):
    #     # mpe = self.options.mpe
        
    #     d0 = data[0]
    #     ch = d0 & 0x0F
    #     msg = (data[0] & 0xF0) >> 4
    #     if force_channel:
    #         data[0] = (d0 & 0xF0) + (force_channel-1)
    #     elif not self.is_mpe():
    #         data[0] = (d0 & 0xF0) + (self.options.one_channel-1)
    #     row = None
    #     col = None

    #     within_hardware_split = False
    #     if self.options.hardware_split:
    #         if self.board_w == 25: # 200
    #             left_width = 11
    #             right_width = 14
    #             if ch >= 8:
    #                 width = right_width
    #                 within_hardware_split = True
    #             else:
    #                 width = left_width
    #         else:
    #             left_width = 8
    #             right_width = 8
    #             if ch >= 8:
    #                 width = right_width
    #                 within_hardware_split = True
    #             else:
    #                 width = left_width
    #     else:
    #         width = self.board_w
        
    #     # if not mpe:
    #     #     row = ch % 8
    #     #     col = ch // 8
    #     # if mpe:
    #     row = data[1] // width
    #     col = data[1] % width
    #     if within_hardware_split:
    #         data[1] += left_width
    #     data[1] = col + 30 + 2.5 * row
    #     data[1] *= 2
    #     data[1] = int(data[1])
    #     if within_hardware_split:
    #         data[1] += left_width * 2
    #     # else:
    #     #     data[1] *= 2
    #     #     try:
    #     #         data[1] -= row * 5
    #     #     except IndexError:
    #     #         pass
        
    #     return col, row
    
    def cb_midi_in(self, data, timestamp, force_channel=None):
        """LinnStrument MIDI Callback"""
        # d4 = None
        # if len(data)==4:
        #     d4 = data[3]
        #     data = data[:3]
        d0 = data[0]
        # print(data)
        ch = d0 & 0x0F
        msg = (data[0] & 0xF0) >> 4
        row = None
        col = None
        # if not self.options.mpe:
        #     row = ch % 8
        #     col = ch // 8
        if msg == 9:  # note on
            if data[2] == 0: # 0 vel
                self.note_off(data, timestamp)
            else:
                self.note_on(data, timestamp)
            # print('note on: ', data)
        elif msg == 8:  # note off
            self.note_off(data, timestamp)
        elif 0xF0 <= msg <= 0xF7:  # sysex
            # rewrite the output channel based on app's MPE settings
            self.midi_write(self.midi_out, data, timestamp)
        else:
            # rewrite the output channel based on app's MPE settings
            if force_channel:
                data[0] = (d0 & 0xF0) | (force_channel-1)
            elif not self.is_mpe():
                data[0] = (d0 & 0xF0) | (self.options.one_channel-1)
            
            skip = False
            if msg == 14:
                if self.is_split():
                    # experimental: ignore pitch bend for a certain split
                    split_chan = self.notes[ch].split
                    if self.options.stable_left and split_chan == 0:
                        data[1] = 0
                        data[2] = 64
                        self.midi_write(self.midi_out, data, timestamp)
                        skip = True
                    if self.options.stable_right and split_chan == 1:
                        data[1] = 0
                        data[2] = 64
                        self.midi_write(self.split_out, data, timestamp)
                        skip = True
                
            # use_stabilizer = self.options.stabilizer
            # bend = decompose_pitch_bend([data[1], data[2]])
            # print('bend', bend)
            # note_ofs = bend * 24
            # print(' note_ofs', note_ofs)
            # closest_ofs = round(note_ofs)
            # print(' closest_ofs', closest_ofs)
            # diff = note_ofs - closest_ofs # diff between note and tuning
            # diff **= 0.9 # bend the curve
            # print(' diff', diff)
            # note_ofs = closest_ofs + diff
            # bend = note_ofs / 24
            # print(' end bend', bend)
            # data[1], data[2] = compose_pitch_bend(bend)
            # print(data[1], data[2])
            # semitones = pitch_bend_to_semitones(bend)
            # print('pitch', bend, semitones)
            # stabilized = True
            
            # This block has to happen before the below block rewrites y axis to pitch bend
            if self.options.y_bend:
                pb_range = self.options.bend_range * 2
                bend_threshold = 1 # units
                if msg == 14:
                    # if y-bending enabled, rewrite pitch bend based on y bend value
                    note = self.notes[ch]
                    # if note.y_bend > EPSILON:
                    val = decompose_pitch_bend((data[1], data[2]))
                    note.bend = val
                    val += note.y_bend / pb_range
                    data[1], data[2] = compose_pitch_bend(val)

                if msg == 11 and data[1] == 74:
                    # print(data[2])
                    if data[2] > 127 - bend_threshold:
                        bend = (data[2] - (127 - bend_threshold)) / bend_threshold
                    elif data[2] <= bend_threshold:
                        # bend down?
                        # bend = -(bend_threshold - data[2]) / bend_threshold
                        bend = None
                    else:
                        bend = None
                    note = self.notes[ch]
                    data = [0xe0 | ch,0,0]
                    if force_channel:
                        data[0] = 0xe0 | (force_channel-1)
                    elif not self.is_mpe():
                        data[0] = 0xe0 | (self.options.one_channel-1)
                    if bend is not None:
                        if bend > 0.9:
                            bend = 1.0
                        elif bend < -0.9:
                            bend = -1.0
                        note.y_bend = bend
                        data[1], data[2] = compose_pitch_bend(note.bend + note.y_bend / pb_range)
                    else:
                        note.y_bend = 0.0
                        data[1], data[2] = compose_pitch_bend(note.bend + note.y_bend / pb_range)


            if skip:
                pass
            elif msg == 11 and data[1] == 64:  # sustain pedal
                if self.is_split():
                    for dev in self.sustainable_devices():
                        self.midi_write(dev, data, timestamp)
                else:
                    self.midi_write(self.midi_out, data, timestamp)
            elif self.is_split(): # everything else (if split)...
                # print('ch', ch)
                try:
                    note = self.notes[ch]
                except:
                    note = None
                if ch == 0:
                    self.midi_write(self.midi_out, data, timestamp)
                    self.midi_write(self.split_out, data, timestamp)
                # else:
                #     split_chan = 1 if ch >= 8 else 0
                #     if split_chan:
                #         self.midi_write(self.split_out, data, timestamp)
                #     else:
                #         self.midi_write(self.midi_out, data, timestamp)
                elif note and note.location is not None:
                    col = note.location.x
                    row = note.location.y
                    split_chan = self.channel_from_split(col, row)
                    if split_chan:
                        self.midi_write(self.split_out, data, timestamp)
                    else:
                        self.midi_write(self.midi_out, data, timestamp)
                else:
                    self.midi_write(self.midi_out, data, timestamp)
                    self.midi_write(self.split_out, data, timestamp)
            else:  # everything else (if not split)...
                self.midi_write(self.midi_out, data, timestamp)

    def cb_visualizer(self, data, timestamp):
        """Visualizer MIDI Callback"""
        # print(msg, timestamp)
        ch = data[0] & 0x0F
        msg = data[0] >> 4
        if msg == 9:  # note on
            self.mark(data[1] + self.vis_octave * 12, 1, True)
        elif msg == 8:  # note off
            self.mark(data[1] + self.vis_octave * 12, 0, True)
        # else:
            # print(msg, data)

    def cb_foot(self, data, timestamp):
        """Foot controller MIDI Callback"""
        ch = data[0] & 0x0F
        msg = (data[0] & 0xF0) >> 4
        if msg == 11:
            # change velocity curve
            val = data[1]
            val2 = None
            if val == 27:  # left expr pedal
                self.midi_write(self.midi_out, data, 0)
                if self.is_split():
                    data[1] = 67  # soft pedal
                    self.midi_write(self.split_out, data, 0)
            elif val == 7:  # right expr pedal
                val2 = 1.0 - data[2] / 127
                low = self.options.velocity_curve_low
                high = self.options.velocity_curve_high
                self.velocity_curve_ = low + val2 * (high - low)

    def is_macro_button(self, x, y):
        """Is pad at x, y bound to a macro?"""
        return False
        # return x == 0 and y == 0

    def macro(self, x, y, val):
        """Do macro on x, y pad"""
        if not self.is_macro_button(x, y):
            return False
        if x == 0 and y == 0:
            if val is True:
                return
            if val is False:
                val = 0.0
            self.articulation.set(val)
        return True

    # uses button state events (mk3 pro)
    def cb_launchpad_in(self, lp, event, timestamp=0):
        """Launchpad MIDI Callback"""
        if (lp.mode == "pro" or lp.mode == "promk3") and event[0] >= 255:
        # if event[0] >= 255: # uncomment this for testing pro behavior on launchpad X
            # I'm testing the mk3 method on an lpx, so I'll check this here
            vel = event[2] if lp.mode == 'lpx' else event[1]
            for note in self.note_set:
                self.midi_write(self.midi_out, [160, note, vel], timestamp)
                self.articulation.pressure(vel / 127)
        elif lp.mode == 'lpx' and event[0] >= 255: # pressure
            x = event[0] - 255
            y = 8 - (event[1] - 255)
            vel = event[2]
            note = y * 8 + x
            note += 12
            if not self.is_macro_button(x,  8 - y - 1):
                self.note_on([160, note, event[2]], timestamp, width=8, transpose=lp.transpose, octave=lp.get_octave(), force_channel=self.options.launchpad_channel)
                self.articulation.pressure(vel / 127)
            else:
                self.macro(x, 8 - y - 1, vel / 127)
        elif event[2] == 0: # note off
            x = event[0]
            y = 8 - event[1]
            if 0 <= x < 8 and 0 <= y < 8:
                self.reset_launchpad_light(x, y, launchpad=lp)
                if not self.is_macro_button(x, 8 - y - 1):
                    note = y * 8 + x
                    self.note_off([128, note, event[2]], timestamp, width=8, transpose=lp.transpose, octave=lp.get_octave(), force_channel=self.options.launchpad_channel)
                else:
                    self.macro(x, 8 - y - 1, False)
            else:
                # Launchpad X buttons
                lp.button(x, 8 - y - 1)
        else: # note on
            x = event[0]
            y = 8 - event[1]
            if 0 <= x < 8 and 0 <= y < 8:
                self.set_launchpad_light(x, y, -1, launchpad=lp)
                if not self.is_macro_button(x, 8 - y - 1):
                    note = y * 8 + x
                    self.note_on([144, note, event[2]], timestamp, width=8, transpose=lp.transpose, octave=lp.get_octave(), force_channel=self.options.launchpad_channel)
                else:
                    self.macro(x, 8 - y - 1, True)

    # uses raw events (Launchpad X)
    # def cb_launchpad_in(self, event, timestamp=0):
    #     if event[0] == 144:
    #         # convert to x, y (lower left is 0, 0)
    #         y = event[1] // 10 - 1
    #         x = event[1] % 10 - 1
    #         # convert it to no overlap chromatic
            
    #         self.launchpad_state[y][x] = None
    #         note = y * 8 + x
    #         self.note_off([128, note, event[2]], timestamp, width=8, mpe=True)
    #     elif event[0] == 160:
    #         y = event[1] // 10 - 1
    #         x = event[1] % 10 - 1
    #         state = self.launchpad_state[y][x]
    #         self.launchpad_state[y][x] = event[2]
    #         note = y * 8 + x
    #         if state is None: # just pressed
    #             self.note_on([144, note, event[2]], timestamp, width=8, mpe=True, curve=False)
    #         self.note_on([160, note, event[2]], timestamp, width=8, mpe=True, curve=False)
    #     elif event[0] == 176:
    #         if event == [176, 93, 127, 0]:
    #             self.move_board(-1)
    #             self.dirty = self.dirty_lights = True
    #         elif event == [176, 94, 127, 0]:
    #             self.move_board(1)
    #             self.dirty = self.dirty_lights = True
            
        # if events[0] >= 255:
        #     print("PRESSURE: " + str(events[0]-255) + " " + str(events[1]))
        # else:
        #     if events[1] > 0:
        #         print("PRESSED:  ", end='')
        #     else:
        #         print("RELEASED: ", end='')
        #     print(str(events[0]) + " " + str(events[1]))

    # def save():
    #     self.cfg = ConfigParser(allow_no_value=True)
    #     general = self.cfg['general'] = {}
    #     if self.options.lights:
    #         general['lights'] = ','.join(map(str,self.options.lights))
    #     general['one_channel'] = self.options.one_channel
    #     general['velocity_curve'] = self.options.velocity_curve
    #     general['min_velocity'] = self.options.min_velocity
    #     general['max_velocity'] = self.options.max_velocity
    #     general['mpe'] = self.options.mpe
    #     general['hardware_split'] = self.options.hardware_split
    #     general['show_lowest_note'] = self.options.show_lowest_note
    #     general['midi_out'] = self.options.midi_out
    #     general['split_out'] = self.options.split_out
    #     general['split'] = SPLIT
    #     general['fps'] = self.options.fps
    #     general['sustain'] = SUSTAIN
    #     self.cfg['general'] = general
    #     with open('settings_temp.ini', 'w') as configfile:
    #         self.cfg.write(configfile)

    # def init_launchpad(self):
    #     pattern = [
    #         'ggggbb',
    #         'cggbbb',
    #     ]
        
    #     self.launchpad.LedCtrlXY(x, y+1, lp_col[0], lp_col[1], lp_col[2])

    #     for y in range(1, 9):
    #         for x in range(0, 8):
    #             yy = y - 2
    #             xx = x
    #             yy -= 3
    #             xx -= (8-yy-1)//2
    #             col = pattern[yy%2][xx%6]
    #             if col == 'c': #cyan
    #                 col = [0, 63, 63]
    #             elif col == 'g': #green
    #                 col = [0, 63, 0]
    #             elif col == 'b': #black
    #                 col = [0, 0, 0]
    #             self.launchpad.LedCtrlXY(x, y, col[0], col[1], col[2])

    def sig(self, signal, frame):
        """Signal handler"""
        self.quit()

    def __init__(self):
        Core.CORE = self
        
        signal.signal(signal.SIGINT, self.sig)
        signal.signal(signal.SIGTERM, self.sig)
         
        self.cfg = ConfigParser(allow_no_value=True)
        self.cfg.read("settings.ini")
        try:
            opts = self.cfg["general"]
        except KeyError:
            opts = None

        with open("scales.yaml", 'r') as stream:
            try:
                self.scale_db = yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                error('Cannot load scales.yaml')

        dups = {}
        scale_count = 0
        for scale in self.scale_db:
            notes = scale['notes']
            count = notes.count('x')
            dupes = (scale.get('duplicates') is True) or False
            if not dupes:
                scale_count += count
                for i in range(count):
                    mode_notes = self.rotate_mode(notes, i)
                    try:
                        name = scale['name'] + ' ' + scale['modes'][i]
                    except:
                        name = scale['name'] + ' Mode ' + str(i+1)
                    if mode_notes in dups:
                        print('Duplicate scale: ', dups[mode_notes], ' and ', name)
                        break
                    else:
                        # print(mode_notes, name)
                        dups[mode_notes] = name
            else:
                scale_count += 1

        # print('Scale Count:', scale_count)

        self.options = Settings()

        self.options.column_offset = get_option(opts, "column_offset", DEFAULT_OPTIONS.column_offset)
        self.options.row_offset = get_option(opts, "row_offset", DEFAULT_OPTIONS.row_offset)
        self.options.base_offset = get_option(opts, "base_offset", DEFAULT_OPTIONS.base_offset)

        self.options.colors = get_option(opts, "colors", DEFAULT_OPTIONS.colors)
        self.options.colors = list(self.options.colors.split(","))
        self.options.colors = list(map(lambda x: glm.ivec3(get_color(x)), self.options.colors))

        self.options.launchpad_colors = get_option(opts, "launchpad_colors", DEFAULT_OPTIONS.launchpad_colors)
        if self.options.launchpad_colors:
            self.options.launchpad_colors = list(self.options.launchpad_colors.split(","))
            self.options.launchpad_colors = list(int(x) for x in self.options.launchpad_colors)

        self.options.split_colors = get_option(opts, "split_colors", DEFAULT_OPTIONS.split_colors)
        self.options.split_colors = list(self.options.split_colors.split(","))
        self.options.split_colors = list(map(lambda x: glm.ivec3(get_color(x)), self.options.split_colors))

        # LIGHT = ivec3(127)
        self.options.lights = get_option(opts, "lights", DEFAULT_OPTIONS.lights)
        if self.options.lights:
            self.options.lights = list(
                map(lambda x: int(x), self.options.lights.split(","))
            )
        self.options.lights = list(map(lambda x: 3 if x==7 else x, self.options.lights))

        self.options.split_lights = get_option(
            opts, "split_lights", DEFAULT_OPTIONS.split_lights
        )
        if self.options.split_lights:
            self.options.split_lights = list(
                map(lambda x: int(x), self.options.split_lights.split(","))
            )
        self.options.split_lights = list(map(lambda x: 5 if x==7 else x, self.options.split_lights))

        if len(self.options.colors) != 12:
            error("Invalid color configuration. Make sure you have 12 colors under the colors option or remove it.")
        if len(self.options.split_colors) != 12:
            error("Invalid split color configuration. Make sure you have 12 colors under the split_colors option or remove it.")
        if len(self.options.lights) != 12:
            error("Invalid light color configuration. Make sure you have 12 light colors under the lights option or remove it.")
        if len(self.options.split_lights) != 12:
            error("Invalid light color configuration for split. Make sure you have 12 light colors under the split_lights option or remove it.")

        self.options.one_channel = get_option(
            opts, "one_channel", DEFAULT_OPTIONS.one_channel
        )
        self.options.bend_range = get_option(
            opts, "bend_range", DEFAULT_OPTIONS.bend_range
        )

        if "--lite" in sys.argv:
            self.options.lite = True
        else:
            self.options.lite = get_option(
                opts, "lite", DEFAULT_OPTIONS.lite
            )

        # bend the velocity curve, examples: 0.5=sqrt, 1.0=default, 2.0=squared
        self.options.velocity_curve = get_option(
            opts, "velocity_curve", DEFAULT_OPTIONS.velocity_curve
        )

        # these settings are only used with the foot controller
        self.options.velocity_curve_low = get_option(
            opts, "velocity_curve_low", DEFAULT_OPTIONS.velocity_curve_low
        )  # loudest (!)
        self.options.velocity_curve_high = get_option(
            opts, "velocity_curve_high", DEFAULT_OPTIONS.velocity_curve_high
        )  # quietest (!)

        if self.options.velocity_curve < EPSILON:  # if its near zero, set default
            self.options.velocity_curve = 1.0  # default

        self.options.mark_light = get_option(
            opts, "mark_light", DEFAULT_OPTIONS.mark_light
        )
        self.options.mark_color = get_option(
            opts, "mark_color", DEFAULT_OPTIONS.mark_color
        )
        self.options.mark_color = glm.ivec3(get_color(self.options.mark_color))

        self.options.min_velocity = get_option(
            opts, "min_velocity", DEFAULT_OPTIONS.min_velocity
        )
        self.options.max_velocity = get_option(
            opts, "max_velocity", DEFAULT_OPTIONS.max_velocity
        )
        self.options.show_lowest_note = get_option(
            opts, "show_lowest_note", DEFAULT_OPTIONS.show_lowest_note
        )

        self.options.y_bend = get_option(
            opts, "y_bend", DEFAULT_OPTIONS.y_bend
        )

        # self.options.mpe = get_option(
        #     opts, "mpe", DEFAULT_OPTIONS.mpe
        # ) or get_option(
        #     opts, "no_overlap", DEFAULT_OPTIONS.mpe
        # )
        self.options.vibrato = get_option(opts, "vibrato", DEFAULT_OPTIONS.vibrato)
        self.options.midi_out = get_option(opts, "midi_out", DEFAULT_OPTIONS.midi_out)
        self.options.split_out = get_option(
            opts, "split_out", DEFAULT_OPTIONS.split_out
        )
        self.options.fps = get_option(opts, "fps", DEFAULT_OPTIONS.fps)
        # self.options.fps = get_option(opts, "jazz", DEFAULT_OPTIONS.jazz)
        self.options.chord_analyzer = get_option(opts, "chord_analyzer", DEFAULT_OPTIONS.chord_analyzer)
        self.split_state = self.options.split = get_option(
            opts, "split", DEFAULT_OPTIONS.split
        )
        self.options.foot_in = get_option(opts, "foot_in", DEFAULT_OPTIONS.foot_in)
        # self.options.sustain = get_option(
        #     opts, "sustain", DEFAULT_OPTIONS.sustain
        # )

        # which split the sustain affects
        self.options.sustain_split = get_option(
            opts, "sustain_split", "both"
        )  # left, right, both
        if self.options.sustain_split not in ("left", "right", "both"):
            print("Invalid sustain split value. Settings: left, right, both.")
            sys.exit(1)

        self.options.octave_separation = get_option(opts, "octave_separation", DEFAULT_OPTIONS.octave_separation)
        self.options.octave_split = get_option(opts, "octave_split", DEFAULT_OPTIONS.octave_split)

        hardware_split = False
        self.options.size = get_option(opts, "size", DEFAULT_OPTIONS.size)
        if self.options.size == 128:
            self.options.width = 16
            self.split_point = None
        elif self.options.size == 200:
            self.options.width = 25
            self.split_point = 11
            hardware_split = True
        elif self.options.size < 0: # test hardware split
            self.options.width = 16
            self.split_point = -self.options.size
            hardware_split = True

        # Note: The default below is what is determined by size above.
        # Overriding hardware_split is only useful for 128 user testing 200 behavior
        self.options.hardware_split = get_option(opts, "hardware_split", hardware_split)

        self.options.launchpad = get_option(opts, 'launchpad', True)
        self.options.launchpad_channel = get_option(opts, 'launchpad_channel', 1)
        self.options.experimental = get_option(opts, 'experimental', False)
        self.options.debug = get_option(opts, 'debug', False)
        self.options.stabilizer = get_option(opts, 'stabilizer', False)
        self.options.stable_left = get_option(opts, 'stable_left', False)
        self.options.stable_right = get_option(opts, 'stable_right', False)

        # simulator keys
        self.keys = {}
        i = 0
        for key in "1234567890-=":
            self.keys[ord(key)] = 62 + i
            i += 2
        self.keys[pygame.K_BACKSPACE] = 62 + i
        i = 0
        for key in "qwertyuiop[]\\":
            self.keys[ord(key)] = 57 + i
            i += 2
        i = 0
        for key in "asdfghjkl;'":
            self.keys[ord(key)] = 52 + i
            i += 2
        self.keys[pygame.K_RETURN] = 52 + i
        i = 0
        for key in "zxcvbnm,./":
            self.keys[ord(key)] = 47 + i
            i += 2
        self.keys[pygame.K_RSHIFT] = 47 + i

        # self.panel = CHORD_ANALYZER
        self.panel_sz = 32
        self.status_sz = 32
        # self.status_sz = 32 if self.options.experimental else 0
        self.menu_sz = 32 #96  # full
        self.max_width = 25  # MAX WIDTH OF LINNSTRUMENT
        self.board_h = 8
        self.scale = vec2(64.0)

        self.board_w = self.options.width
        self.board_sz = ivec2(self.board_w, self.board_h)
        self.screen_w = self.board_w * self.scale.x
        self.screen_h = self.board_h * self.scale.y + self.menu_sz + self.status_sz
        self.button_sz = self.screen_w / self.board_w
        self.screen_sz = ivec2(self.screen_w, self.screen_h)

        self.lowest_note = None  # x,y location of lowest note currently pressed
        self.lowest_note_midi = None  # midi number of lowest note currently pressed
        self.octave = 0
        self.out_octave = 0
        self.vis_octave = (
            -2
        )  # this is for both the visualizer and the keyboard simulator marking atm
        self.octave_base = -2
        # self.position.x = 0
        self.position = glm.ivec2(0, 0) # only x is used right now
        self.rotated = False  # transpose -3 whole steps
        self.flipped = False  # vertically shift +1
        self.config_save_timer = 1.0

        self.velocity_curve_ = self.options.velocity_curve

        self.mouse_mark = ivec2(0)
        self.mouse_midi = -1
        self.mouse_midi_vel = None

        self.last_note = None # ivec2
        self.chord = ''

        self.scale_index = 0
        self.mode_index = 0
        self.scale_name = self.scale_db[self.scale_index]['name']
        self.mode_name = self.scale_db[self.scale_index]['modes'][self.mode_index]
        self.scale_notes = self.scale_db[self.scale_index]['notes']
        self.scale_root = 0
        self.tonic = 0
        
        self.program = 0
        self.bank = 0

        self.articulation = Articulation(self)

        self.init_board()

        # load midi file from command line (playiung it is not yet impl)
        # self.midi_in_fn = None
        # self.midifile = None
        # if len(sys.argv) > 1:
        #     self.midi_in_fn = sys.argv[1]
        #     if self.midi_in_fn.to_lower().endswith('.mid'):
        #         self.midifile = mido.MidiFile(midi_fn)

        # self.root = Tk()
        # self.menubar = Menu(self.root)
        # self.filemenu = Menu(self.menubar, tearoff=0)
        # self.filemenu.add_command(label="Open", command=nothing)
        # self.root.config(menu=self.menubar)
        # self.embed = Frame(self.root, width=self.screen_w, height=self.screen_h)
        # self.embed.pack()
        # os.environ['SDL_WINDOWID'] = str(self.embed.winfo_id())
        # self.root.update()
        # self.menubar.add_cascade(label="File", menu=self.filemenu)
        # self.root.protocol("WM_DELETE_WINDOW", self.quit)
        pygame.init()
        pygame.display.set_caption(TITLE)
        self.icon = pygame.image.load('icon.png')
        pygame.display.set_icon(self.icon)
        # if FOCUS:
        #     pygame.mouse.set_visible(0)
        #     pygame.event.set_grab(True)
        if self.options.lite:
            self.screen = Screen(
                self, pygame.display.set_mode((256, 256), pygame.DOUBLEBUF)
            )
        else:
            self.screen = Screen(
                self, pygame.display.set_mode(self.screen_sz, pygame.DOUBLEBUF)
            )

        bs = ivec2(self.button_sz, self.panel_sz)  # // 2 double panel
        self.gui = pygame_gui.UIManager(self.screen_sz)
        y = 0
        self.btn_octave_down = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((2, y), bs), text="<OCT", manager=self.gui
        )
        self.btn_octave_up = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x + 2, y), bs), text="OCT>", manager=self.gui
        )
        self.btn_transpose_down = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 2 + 2, y), (bs.x, bs.y)),
            text='<TR',
            manager=self.gui
        )
        self.btn_transpose_up = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 3 + 2, y), (bs.x, bs.y)),
            text='TR>',
            manager=self.gui
        )
        self.btn_move_left = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 4 + 2, y), bs),
            text="<MOV",
            manager=self.gui,
        )
        self.btn_move_right = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 5 + 2, y), bs),
            text="MOV>",
            manager=self.gui,
        )
        # self.btn_size = pygame_gui.elements.UIButton(
        #     relative_rect=pygame.Rect((bs.x * 4 + 2, y), bs),
        #     text="SIZE",
        #     manager=self.gui,
        # )
        self.btn_rotate = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 6 + 2, y), bs),
            text="ROT",
            manager=self.gui,
        )
        self.btn_flip = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 7 + 2, y), bs),
            text="FLIP",
            manager=self.gui,
        )

        self.btn_split = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 8 + 2, y), (bs.x * 2, bs.y)),
            text="SPLIT: " + ("ON" if self.split_state else "OFF"),
            manager=self.gui,
        )

        self.btn_mpe = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 10 + 2, y), (bs.x * 2, bs.y)),
            text="MPE: " + ("OFF" if self.options.one_channel else "ON"),
            manager=self.gui,
        )


        # if self.options.experimental:
        self.btn_prev_scale = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 12 + 2, y), (bs.x, bs.y)),
            text='<SCL',
            manager=self.gui
        )
        self.btn_next_scale = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 13 + 2, y), (bs.x, bs.y)),
            text='SCL>',
            manager=self.gui
        )

        self.btn_prev_mode = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 14 + 2, y), (bs.x, bs.y)),
            text='<MOD',
            manager=self.gui
        )
        self.btn_next_mode = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 15 + 2, y), (bs.x, bs.y)),
            text='MOD>',
            manager=self.gui
        )
        self.btn_sharps_flats = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 16 + 2, y), (bs.x, bs.y)),
            text='#/b',
            manager=self.gui
        )
        # self.next_scale = pygame_gui.elements.UIButton(
        #     relative_rect=pygame.Rect((bs.x * 11 + 2, y), (bs.x, bs.y)),
        #     text='SCL>',
        #     manager=self.gui
        # )
        # self.scale_label = pygame_gui.elements.UILabel(
        #     relative_rect=pygame.Rect((bs.x * 12 + 2, y), (bs.x, bs.y)),
        #     text='Major',
        #     manager=self.gui
        # )

        # self.chord_label = pygame_gui.elements.UILabel(
        #     relative_rect=pygame.Rect((0, self.screen_h - self.status_sz), (self.screen_w, self.status_sz)),
        #     text='test',
        #     manager=self.gui
        # )
        # self.chord_label.centerx = self.screen_w/2

        # y = bs.y * 2
        # self.note_buttons = [None] * 12
        # for n in range(12):
        #     end_pos = n*2*bs.x//3 + 2*bs.x//3
        #     self.note_buttons[n] = pygame_gui.elements.UIButton(
        #         relative_rect=pygame.Rect((2+n*2*bs.x//3, y), (2*bs.x//3, bs.y)),
        #         text=NOTES[n],
        #         manager=self.gui
        #     )
        
        # self.slider_velocity = pygame_gui.elements.UIHorizontalSlider (
        #     relative_rect=pygame.Rect((bs.x*2+2,y+bs.y),(bs.x*2,bs.y)),
        #     start_value=self.options.velocity_curve,
        #     value_range=[0,1],
        #     manager=self.gui
        # )

        # pygame.midi.init()

        self.out = []
        self.midi_in = None
        ins = []
        outs = []
        # in_devs = [
        #     'linnstrument',
        #     'visualizer'
        # ]
        # out_devs = [
        #     'linnstrument',
        #     self.options.midi_out,
        #     'midimech'
        # ]
        # for i in range(pygame.midi.get_count()):
        #     info = pygame.midi.get_device_info(i)
        #     # print(info)
        #     if info[2]==1:
        #         ins.append((i,str(info[1])))
        #     if info[3]==1:
        #         outs.append((i,str(info[1])))

        # innames = []
        # for inx in ins:
        #     innames += [str(inx[1])]
        #     print('in: ', inx)

        self.linn_out = None
        self.midi_out = None
        self.split_out = None
        self.use_sharps = True
        self.NOTES = NOTES_SHARPS


        outnames = rtmidi2.get_out_ports()
        for i in range(len(outnames)):
            name = outnames[i]
            name_lower = name.lower()
            # print(name_lower)
            if "linnstrument" in name_lower:
                print("Instrument (Out): " + name)
                self.linn_out = rtmidi2.MidiOut()
                try:
                    self.linn_out.open_port(i)
                except:
                    print("Unable to open LinnStrument")
            elif self.options.split_out and self.options.split_out in name_lower:
                print("Split (Out): " + name)
                self.split_out = rtmidi2.MidiOut()
                self.split_out.open_port(i)
            elif self.options.midi_out in name_lower:
                print("Loopback (Out): " + name)
                self.midi_out = rtmidi2.MidiOut()
                self.midi_out.open_port(i)

        self.midi_in = None
        self.visualizer = None
        
        # self.gamepad = None
        # if self.options.experimental:
        #     pygame.joystick.init()
        #     if pygame.joystick.get_count() > 0:
        #         self.gamepad = Gamepad(self, 0)
        #         print('Gamepad initialized')

        innames = rtmidi2.get_in_ports()
        for i in range(len(innames)):
            name = innames[i]
            name_lower = name.lower()
            if "visualizer" in name_lower:
                print("Visualizer (In): " + name)
                self.visualizer = rtmidi2.MidiIn()
                self.visualizer.callback = self.cb_visualizer
                self.visualizer.open_port(i)
            elif "linnstrument" in name_lower:
                print("Instrument (In): " + name)
                self.midi_in = rtmidi2.MidiIn()
                self.midi_in.callback = self.cb_midi_in
                self.midi_in.open_port(i)
            elif self.options.foot_in and self.options.foot_in in name_lower:
                print("Foot Controller (In): " + name)
                self.foot_in = rtmidi2.MidiIn()
                self.foot_in.open_port(i)
                self.foot_in.callback = self.cb_foot

        self.launchpads = []
        num_launchpads = 0
        if self.options.launchpad:
            launchpads = []
            lp = launchpad.LaunchpadProMk3()
            if lp.Check(0):
                if lp.Open(0):
                    self.launchpads += [Launchpad(self, lp, "promk3", num_launchpads)]
                    num_launchpads += 1
            lp = launchpad.LaunchpadPro()
            if lp.Check(0):
                if lp.Open(0):
                    self.launchpads += [Launchpad(self, lp, "pro", num_launchpads)]
                    num_launchpads += 1
            lp = launchpad.LaunchpadLPX()
            if lp.Check(1):
                lp = launchpad.LaunchpadLPX()
                if lp.Open(1):
                    self.launchpads += [Launchpad(self, lp, "lpx", num_launchpads)]
                    num_launchpads += 1
                if launchpad.LaunchpadLPX().Check(3):
                    lp = launchpad.LaunchpadLPX()
                    if lp.Open(3): # second
                        self.launchpads += [Launchpad(self, lp, "lpx", num_launchpads, self.options.octave_separation)]
                        num_launchpads += 1
        
        if self.launchpads:
            print('Launchpads:', len(self.launchpads))

        self.done = False

        for lp in self.launchpads:
            lp.set_lights()

        # if self.launchpad:
        #     # use the alternate colors
        #     self.options.colors = get_option(opts, "colors", DEFAULT_OPTIONS.colors_alt)
        #     self.options.colors = list(self.options.colors.split(","))
        #     self.options.colors = list(map(lambda x: glm.ivec3(get_color(x)), self.options.colors))
        
        if not self.midi_out:
            error(
                "No MIDI output device detected.  Install a midi loopback device and name it 'midimech'!"
            )

        self.dirty = True
        self.dirty_lights = True
        self.dirty_chord = False
        # self.dirty_left_chord = False

        w = self.max_width
        h = self.board_h
        self.board = [[0 for x in range(w)] for y in range(h)]
        self.mark_lights = [[False for x in range(w)] for y in range(h)]
        self.launchpad_state = [[None for x in range(8)] for y in range(8)]

        self.font = pygame.font.Font(None, FONT_SZ)

        # self.retro_font = pygame.font.Font("PressStart2P.ttf", FONT_SZ)
        self.clock = pygame.time.Clock()

        # if move_board:
        #     self.move_board(move_board)

        # self.setup_lights()

        self.setup_rpn()
        # self.test()

    def midi_mode_rpn(self, on=True):
        if on:
            self.rpn(0, 1 if self.is_mpe() else 0)
            self.rpn(100, 1 if self.is_mpe() else 0)
        else:
            self.rpn(0, 1)
            self.rpn(100, 1)

    def setup_rpn(self, on=True):
        """Sets all relevant RPN settings"""
        if on:
            self.midi_mode_rpn()
            # if self.options.mpe:
            self.mpe_rpn()
            self.transpose_rpn()
            # else:
            #     self.rows_rpn()
            self.bend_rpn()
            self.split_rpn(self.options.hardware_split)
        else:
            self.midi_mode_rpn(False)
            self.transpose_rpn(False)
            self.mpe_rpn(False)
            self.bend_rpn(False)
            self.split_rpn(False)

    def split_rpn(self, on=True):
        """Sets up RPN for hardware split (used on LinnStrument 200)"""
        if self.options.hardware_split:
            self.rpn(200, 1 if on else 0) # split active
            self.rpn(202, self.split_point + 1)

            # lights
            self.send_ls_cc(0, 20, 0)
            self.send_ls_cc(0, 21, 1)
            self.send_ls_cc(0, 22, 7 if on else 0)
        else:
            self.rpn(200, 0)
            self.rpn(202, self.split_point if self.split_point else 8)

    def rpn(self, num, value):
        if not self.linn_out:
            return
        """LinnStrument RPN"""
        num_msb, num_lsb = decode_value(num)
        value_msb, value_lsb = decode_value(value)
        self.midi_write(self.linn_out, [176, 99, num_msb])
        self.midi_write(self.linn_out, [176, 98, num_lsb])
        self.midi_write(self.linn_out, [176, 6, value_msb])
        self.midi_write(self.linn_out, [176, 38, value_lsb])
        self.midi_write(self.linn_out, [176, 101, 127])
        self.midi_write(self.linn_out, [176, 100, 127])
        time.sleep(0.05)

    def mpe_rpn(self, on=True):
        """Sets up MPE settings (except MIDI mode)"""
        if not self.linn_out:
            return

        if on:
            # self.rpn(0, 1)
            # self.rpn(100, 1)
            self.rpn(227, 0) # no overlap

            if self.options.hardware_split:
                # left side channels
                self.rpn(1, 1)
                self.rpn(2, 0)
                for x in range(3, 10):
                    self.rpn(x, 1)
                for x in range(10, 18):
                    self.rpn(x, 0)

                # right side channels
                self.rpn(101, 16) # main=16
                for x in range(110, 117):
                    self.rpn(x, 1)
                self.rpn(117, 0) # 16 off
            else:
                # left side only
                self.rpn(1, 1)
                self.rpn(2, 0)
                for x in range(3, 18):
                    self.rpn(x, 1)

        else:
            self.rpn(227, 5)

    # def rows_rpn(self):
    #     self.rpn(0, 2)
    #     self.rpn(100, 2)

    def bend_rpn(self, on=True):
        if on:
            # set bend range for both split
            self.rpn(19, self.options.bend_range)
            self.rpn(119, self.options.bend_range)
        else:
            # reset bend range for both splits
            self.rpn(19, 48)
            self.rpn(119, 48)
    
    def transpose_rpn(self, on=True):
        if on:
            # set transpose in both splits
            self.rpn(36, 2)
            self.rpn(37, 13)
            self.rpn(136, 2)
            self.rpn(137, 13)

            # turn transpose light off
            self.send_ls_cc(0, 20, 0)
            self.send_ls_cc(0, 21, 4)
            self.send_ls_cc(0, 22, 7)

        else:
            # reset transpose in both splits
            self.rpn(36, 5)
            self.rpn(37, 7)
            self.rpn(136, 5)
            self.rpn(137, 7)

    # def test(self):
    #     self.transpose_rpn()

    def move_board(self, val):
        self.send_all_notes_off()
        
        aval = abs(val)
        if aval > 1:  # more than one shift
            assert False
            # sval = sign(val)
            # for rpt in range(aval):
            #     self.move_board(sval)
            #     self.position.x += sval
        elif val == 1:  # shift right (add column left)
            for y in range(len(self.board)):
                self.board[y] = [0] + self.board[y][:-1]
            self.position.x += val
        elif val == -1:  # shift left (add column right)
            for y in range(len(self.board)):
                self.board[y] = self.board[y][1:] + [0]
            self.position.x += val
        self.dirty = self.dirty_lights = True

    def quit(self):
        self.reset_lights()
        self.setup_rpn(False)
        self.done = True

    def clear_marks(self, use_lights=False):
        y = 0
        for row in self.board:
            x = 0
            for x in range(len(row)):
                idx = self.get_note_index(x, y)
                try:
                    self.board[y][x] = False
                except IndexError:
                    pass
                if use_lights:
                    # if state:
                    #     self.set_light(x, y, 1)
                    # else:
                    self.reset_light(x, y)
            y += 1
        self.dirty = True
        if use_lights:
            self.dirty_lights = True

    def mark_xy(self, x, y, state, use_lights=False):
        if self.flipped:
            y -= 1
        # print(x, y)
        idx = self.get_note_index(x, y)
        try:
            self.board[y + self.flipped][x] = state
        except IndexError:
            print("mark_xy: Out of range")
            pass
        if use_lights:
            if state:
                self.set_light(x, y, self.options.mark_light, mark=True)
            else:
                self.reset_light(x, y)
        self.dirty = True

    def mark(self, midinote, state, use_lights=False, only_row=None):
        if only_row is not None:
            only_row = self.board_h - only_row - 1 - self.flipped  # flip
            try:
                rows = [self.board[only_row]]
                y = only_row
            except IndexError:
                rows = self.board
                y = 0
        else:
            rows = self.board
            y = 0
        for row in rows:
            x = 0
            for x in range(-1 * self.position.x, len(row)-self.position.x): #this band aids bug for 1 move right                
                idx = self.get_note_index(x, y, transpose=False)
                # print(x, y, midinote%12, idx)
                if midinote % 12 == idx:
                    octave = self.get_octave(x, y)
                    if octave == midinote // 12:
                        # print(octave)
                        self.board[y + self.flipped][x + self.position.x] = state
                        if use_lights:
                            if state:
                                self.set_light(x, y, self.options.mark_light, mark=True)
                            else:
                                self.reset_light(x, y)
            y += 1
        self.dirty = True

    def resize(self):
        self.board_sz = ivec2(self.board_w, self.board_h)
        self.screen_w = self.board_w * self.scale.x
        self.screen_h = self.board_h * self.scale.y + self.menu_sz + self.status_sz
        self.button_sz = self.screen_w / self.board_w
        self.screen_sz = ivec2(self.screen_w, self.screen_h)
        self.screen = Screen(self, pygame.display.set_mode(self.screen_sz))
        self.dirty_lights = True

    def channel_from_split(self, col, row, force=False):
        if not force and not self.is_split():
            return 0
        w = self.board_w
        col += 1  # move start point from C to A#
        col -= (row + 1) // 2  # make the split line diagonal
        ch = 0 if col < w // 2 else 1  # channel 0 to 1 depending on split
        return ch

    def is_split(self):
        # TODO: make this work with hardware overlap (non-mpe)
        return self.split_state and self.split_out

    def set_tonic(self, val):
        self.send_all_notes_off()
        
        self.tonic = val
        # print('val', val)
        # odd = (self.tonic % 2 == 1)
        # self.tonic = val
        # print('new tonic', self.tonic)
        # new_odd = (self.tonic % 2 == 1)
        # # if odd != new_odd:
        # #     self.flipped = not self.flipped
        # if new_odd:
        #     self.position.x = (self.tonic // 2 - 3) % 6
        #     self.position.x -= 6
        # else:
        #     self.position.x = (self.tonic // 2) % 6
        # print('new pos', self.position.x)
        
        self.dirty = self.dirty_lights = True

    def logic(self, dt):
        # keys = pygame.key.get_pressed()

        for lp in self.launchpads:
            # while True:
            #     events = self.launchpad.EventRaw()
            #     if events != []:
            #         for ev in events:
            #             self.cb_launchpad_in(ev[0], ev[1])
            #     else:
            #         break
            while True:
                event = lp.out.ButtonStateXY(returnPressure = True)
                if event:
                    self.cb_launchpad_in(lp, event)
                else:
                    break
        
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.quit()
                break
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    self.quit()
                elif ev.key == pygame.K_F1:
                    self.clear_marks(use_lights=True)
                    self.send_all_notes_off()
                else:
                    try:
                        n = self.keys[ev.key]
                        n -= 12
                        n += self.octave * 12
                        self.mark(n + self.vis_octave * 12, 1, True)
                        data = [0x90, n, 127]
                        # TODO: add split for mouse?
                        if self.midi_out:
                            self.midi_write(self.midi_out, data, 0)
                    except KeyError:
                        pass
            elif ev.type == pygame.KEYUP:
                try:
                    n = self.keys[ev.key]
                    n -= 12
                    n += self.octave * 12
                    self.mark(n + self.vis_octave * 12, 0, True)
                    data = [0x80, n, 0]
                    if self.midi_out:
                        # TODO: add split for mouse?
                        self.midi_write(self.midi_out, data, 0)
                except KeyError:
                    pass

            # else:
                # if self.gamepad and ev.type in (\
                #         pygame.JOYAXISMOTION,
                #         pygame.JOYBALLMOTION,
                #         pygame.JOYBUTTONDOWN,
                #         pygame.JOYBUTTONUP,
                #         pygame.JOYHATMOTION
                #     ):
                #         self.gamepad.event(ev)
                
            if not self.options.lite:
                if ev.type == pygame.MOUSEMOTION:
                    x, y = ev.pos
                    y -= self.menu_sz
                    self.mouse_hover(x, y)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    x, y = ev.pos
                    y -= self.menu_sz
                    if ev.button == 1:
                        self.mouse_press(x, y)
                    elif ev.button == 2:
                        self.mouse_release(x, y)
                    elif ev.button == 3:
                        self.mouse_hold(x, y)
                elif ev.type == pygame.MOUSEBUTTONUP:
                    self.mouse_release()
                elif ev.type == pygame_gui.UI_BUTTON_PRESSED:
                    if ev.ui_element == self.btn_octave_down:
                        self.octave -= 1
                        self.dirty = self.dirty_lights = True
                        self.clear_marks(use_lights=False)
                    elif ev.ui_element == self.btn_octave_up:
                        self.octave += 1
                        self.dirty = self.dirty_lights = True
                        self.clear_marks(use_lights=False)
                    elif ev.ui_element == self.btn_move_left:
                        self.move_board(1)
                        self.clear_marks(use_lights=False)
                    elif ev.ui_element == self.btn_move_right:
                        self.move_board(-1)
                        self.clear_marks(use_lights=False)
                    # elif ev.ui_element == self.btn_mode:
                    #     # TODO: toggle mode
                    #     self.dirty = True
                    # elif ev.ui_element == self.btn_size:
                    #     if self.board_w == 16:
                    #         self.board_w = 25
                    #         self.resize()
                    #     else:
                    #         self.board_w = 16
                    #         self.resize()
                    #     self.dirty = True
                    elif ev.ui_element == self.btn_rotate:
                        if self.rotated:
                            self.position.x += 3
                            self.rotated = False
                        else:
                            self.position.x -= 3
                            self.rotated = True
                        self.dirty = self.dirty_lights = True
                        self.clear_marks(use_lights=False)
                    elif ev.ui_element == self.btn_flip:
                        self.flipped = not self.flipped
                        self.dirty = self.dirty_lights = True
                        self.clear_marks(use_lights=False)
                    elif ev.ui_element == self.btn_split:
                        if self.split_out:
                            self.split_state = not self.split_state
                            self.btn_split.set_text(
                                "SPLIT: " + ("ON" if self.split_state else "OFF")
                            )
                            self.dirty = self.dirty_lights = True
                        else:
                            print("You need to add another MIDI loopback device called 'split'")
                    elif ev.ui_element == self.btn_mpe:
                        # self.split_state = not self.split_state
                        self.options.one_channel = 0 if self.options.one_channel else 1
                        # one_channel being non-zero means we're using MPE
                        self.btn_mpe.set_text(
                            "MPE: " + ("OFF" if self.options.one_channel else "ON")
                        )
                        self.midi_mode_rpn()
                        self.dirty = True
                    elif ev.ui_element == self.btn_transpose_down:
                        self.set_tonic(self.tonic - 1)
                    elif ev.ui_element == self.btn_transpose_up:
                        self.set_tonic(self.tonic + 1)
                    elif ev.ui_element == self.btn_next_scale:
                        self.next_scale()
                    elif ev.ui_element == self.btn_prev_scale:
                        self.prev_scale()
                    elif ev.ui_element == self.btn_next_mode:
                        self.next_mode()
                    elif ev.ui_element == self.btn_prev_mode:
                        self.prev_mode()
                    elif ev.ui_element == self.btn_sharps_flats:
                        self.toggle_sharps_flats()
                # elif ev.type == pygame_gui.UI_HORIZONTAL_SLIDER_MOVED:
                #     if ev.ui_element == self.slider_velocity:
                #         global self.options.velocity_curve
                #         self.options.velocity_curve = ev.value
                #         self.config_save_timer = 1.0

                self.gui.process_events(ev)
        
        if self.launchpads:
            self.articulation.logic(dt)

        # if self.gamepad:
        #     self.gamepad.logic(dt)

        # figure out the lowest note to highlight it
        # if self.options.show_lowest_note:
        #     old_lowest_note = self.lowest_note
        #     old_lowest_note_midi = self.lowest_note_midi
        #     self.lowest_note = None
        #     self.lowest_note_midi = None
        #     note_count = 0
        #     for y, row in enumerate(self.board):
        #         for x, cell in enumerate(row):
        #             if cell:
        #                 note_idx = self.get_note_index(x, y)
        #                 note_num = note_idx + 12 * self.octaves[y][x]
        #                 if (
        #                     not self.lowest_note_midi
        #                     or note_num < self.lowest_note_midi
        #                 ):
        #                     self.lowest_note = NOTES[note_idx]
        #                     self.lowest_note_midi = note_num
        #                 note_count += 1

        # if self.dirty:
        #     self.init_board()

        if self.dirty_lights:
            self.setup_lights()
            self.dirty_lights = False

        # lowest note changed?
        # if self.options.show_lowest_note:
        #     if self.lowest_note != old_lowest_note:
        #         if old_lowest_note:
        #             # reset lights for previous lowest note
        #             for y, row in enumerate(self.board):
        #                 for x, cell in enumerate(row):
        #                     if self.get_note(x, y) == old_lowest_note:
        #                         self.reset_light(x, y)
        #         if self.lowest_note:
        #             # set lights for new lowest note
        #             for y, row in enumerate(self.board):
        #                 for x, cell in enumerate(row):
        #                     if self.get_note(x, y) == self.lowest_note:
        #                         self.set_light(x, y, 9)

        # # if self.config_save_timer > 0.0:
        # #     self.config_save_timer -= dt
        # #     if self.config_save_timer <= 0.0:
        # #         save()

        if not self.options.lite:
            # for note in self.notes:
            #     if note.location is None:
            #         continue
            #     note.logic(dt)

            # chord analysis for jazz mod
            # if self.options.jazz:
            #     if self.dirty_chord:
            #         self.left_chord = self.analyze(self.left_chord_notes)
            
            # chord analyzer
            if self.options.chord_analyzer:
                if self.dirty_chord:
                    self.chord = self.analyze(self.chord_notes)

            self.dirty_chord = False
        
            self.gui.update(dt)

    def analyze(self, chord_notes):
        notes = []
        r = ''
        for i, note in enumerate(chord_notes):
            if note:
                n = mp.degree_to_note(i)
                notes.append(n)
        if notes:
            r = mp.alg.detect(mp.chord(notes))
            # try:
            #     r = r[0:self.chord.index(' sort')]
            # except ValueError:
            #     pass
            # if self.chord.startswith('note '):
            #     r = r[len('note '):-1]
        else:
            r = ''
        self.dirty = True
        return r

    def sustainable_devices(self):
        if not self.is_split() or not self.options.sustain_split:
            return [self.midi_out]
        if self.options.sustain_split == "left":
            return [self.midi_out]
        if self.options.sustain_split == "right":
            return [self.split_out]
        if self.options.sustain_split == "both":
            return [self.midi_out, self.split_out]
        return [self.midi_out]

    def render(self):
        if not self.dirty:
            return False

        if self.options.lite:
            self.screen.surface.blit(self.icon, (0,0,256,256))
            return True
        
        self.dirty = False

        self.screen.surface.fill((0, 0, 0))
        b = 2  # border
        sz = self.screen_w / self.board_w
        y = 0
        rad = int(sz // 2 - 8)

        for row in self.board:
            x = 0
            for cell in row:
                # write text
                note = self.get_note(x, y, True)

                split_chan = self.channel_from_split(x, y)

                # note = str(self.get_octave(x, y)) # show octave
                # brightness = 1.0 if cell else 0.5

                col = None

                # if cell:
                #     col = ivec3(255,0,0)
                # else:
                #     col = self.get_color(x, y)
                lit_col = ivec3(255, 0, 0)
                unlit_col = copy.copy(self.get_color(x, y) or ivec3(0))
                black = unlit_col == ivec3(0)
                inner_col = copy.copy(unlit_col)
                for i in range(len(unlit_col)):
                    unlit_col[i] = min(255, unlit_col[i] * 1.5)

                ry = y + self.menu_sz  # real y
                # pygame.gfxdraw.box(self.screen.surface, [x*sz + b, self.menu_sz + y*sz + b, sz - b, sz - b], unlit_col)
                rect = [x * sz + b, self.menu_sz + y * sz + b, sz - b, sz - b]
                inner_rect = [rect[0] + 4, rect[1] + 4, rect[2] - 8, rect[3] - 8]
                pygame.draw.rect(self.screen.surface, unlit_col, rect, border_radius=8)
                pygame.draw.rect(
                    self.screen.surface, inner_col, inner_rect, border_radius=8
                )
                if not black:
                    pygame.draw.rect(
                        self.screen.surface,
                        BORDER_COLOR,
                        rect,
                        width=2,
                        border_radius=8,
                    )
                else:
                    pygame.draw.rect(
                        self.screen.surface, vec3(24), rect, width=2, border_radius=8
                    )
                if cell:
                    circ = ivec2(
                        int(x * sz + b / 2 + sz / 2),
                        int(self.menu_sz + y * sz + b / 2 + sz / 2),
                    )
                    pygame.gfxdraw.aacircle(
                        self.screen.surface,
                        circ.x + 1,
                        circ.y - 1,
                        rad,
                        ivec3(255, 0, 0),
                    )
                    pygame.gfxdraw.filled_circle(
                        self.screen.surface,
                        circ.x + 1,
                        circ.y - 1,
                        rad,
                        ivec3(255, 0, 0),
                    )

                    pygame.gfxdraw.aacircle(
                        self.screen.surface, circ.x - 1, circ.y + 1, rad, ivec3(0)
                    )
                    pygame.gfxdraw.filled_circle(
                        self.screen.surface, circ.x - 1, circ.y + 1, rad, ivec3(0)
                    )

                    pygame.gfxdraw.filled_circle(
                        self.screen.surface, circ.x, circ.y, rad, lit_col
                    )
                    pygame.gfxdraw.aacircle(
                        self.screen.surface, circ.x, circ.y, rad, lit_col
                    )

                    pygame.gfxdraw.filled_circle(
                        self.screen.surface,
                        circ.x,
                        circ.y,
                        int(rad * 0.9),
                        ivec3(200, 0, 0),
                    )
                    pygame.gfxdraw.aacircle(
                        self.screen.surface,
                        circ.x,
                        circ.y,
                        int(rad * 0.9),
                        ivec3(200, 0, 0),
                    )

                text = self.font.render(note, True, (0, 0, 0))
                textpos = text.get_rect()
                textpos.x = x * sz + sz // 2 - FONT_SZ // 4
                textpos.y = self.menu_sz + y * sz + sz // 2 - FONT_SZ // 4
                textpos.x -= 1
                textpos.y += 1
                self.screen.surface.blit(text, textpos)

                text = self.font.render(note, True, ivec3(255))
                textpos = text.get_rect()
                textpos.x = x * sz + sz // 2 - FONT_SZ // 4
                textpos.y = self.menu_sz + y * sz + sz // 2 - FONT_SZ // 4
                textpos.x += 1
                textpos.y -= 1
                self.screen.surface.blit(text, textpos)

                text = self.font.render(note, True, ivec3(200))
                textpos = text.get_rect()
                textpos.x = x * sz + sz // 2 - FONT_SZ // 4
                textpos.y = self.menu_sz + y * sz + sz // 2 - FONT_SZ // 4
                self.screen.surface.blit(text, textpos)

                x += 1
            y += 1

        # if self.gamepad:
        #     pos = self.gamepad.positions()
        #     # gp_pos.y = self.board_h - y - 1
            
        #     circ = [None] * 2
        #     for i in range(2):
        #         circ[i] = ivec2(
        #             int(pos[i].x * sz + b / 2 + sz / 2),
        #             int(self.menu_sz + pos[i].y * sz + b / 2 + sz / 2),
        #         )
                
        #         pygame.gfxdraw.aacircle(
        #             self.screen.surface,
        #             circ[i].x + 1,
        #             circ[i].y - 1,
        #             rad,
        #             ivec3(0, 255, 0),
        #         )
        #         # pygame.gfxdraw.filled_circle(
        #         #     self.screen.surface,
        #         #     circ[i].x + 1,
        #         #     circ[i].y - 1,
        #         #     rad,
        #         #     ivec3(0, 255, 0),
        #         # )

        # if self.options.experimental:
        text = self.font.render(self.scale_name, True, ivec3(127))
        textpos = text.get_rect()
        textpos.x = self.screen_w*1/4 - textpos[2]/2
        textpos.y = self.screen_h - self.status_sz*3/4
        self.screen.surface.blit(text, textpos)

        text = self.font.render(self.mode_name, True, ivec3(127))
        textpos = text.get_rect()
        textpos.x = self.screen_w*2/4 - textpos[2]/2
        textpos.y = self.screen_h - self.status_sz*3/4
        self.screen.surface.blit(text, textpos)

        chord = self.chord or '-'
        text = self.font.render(chord, True, ivec3(127))
        textpos = text.get_rect()
        textpos.x = self.screen_w*3/4 - textpos[2]/2
        textpos.y = self.screen_h - self.status_sz*3/4
        self.screen.surface.blit(text, textpos)

        # if CHORD_ANALYZER:
        #     self.render_chords()

    # def render_chords(self):
    #     sz = self.screen_w / self.board_w
    #     chords = set()
    #     for y, row in enumerate(self.board):
    #         ry = y + self.menu_sz # real y
    #         for x, cell in enumerate(row):
    #             # root_pos = ivec2(0,0)
    #             for name, inversion_list in CHORD_SHAPES.items():
    #                 for shape in inversion_list:
    #                     next_chord = False
    #                     polygons = []
    #                     polygon = []
    #                     root = None
    #                     for rj, chord_row in enumerate(shape):
    #                         for ri, ch in enumerate(chord_row):
    #                             try:
    #                                 mark = self.board[y+rj][x+ri]
    #                             except:
    #                                 polygon = []
    #                                 next_chord = True
    #                                 break
    #                             # mark does not exist (not this chord)
    #                             if ch=='x':
    #                                 root = ivec2(x+ri, y+rj)
    #                             if not mark and ch in 'ox':
    #                                 next_chord=True # double break
    #                                 polygon = []
    #                                 break
    #                             # polygon += [ivec2((x+ri)*sz, (y+rj)*sz+self.menu_sz)]
    #                         if next_chord: # double break
    #                             break
    #                         # if polygon:
    #                         #     polygons += [polygon]
    #                     if not next_chord:
    #                         # for poly in polygons:
    #                         #     pygame.draw.polygon(self.screen.surface, ivec3(0,255,0), poly, 2)
    #                         note = self.get_note_index(*root)
    #                         chords.add((note, name))

    # if chords:
    #     name = ', '.join(NOTES[c[0]] + c[1] for c in chords) # concat names
    #     text = self.font.render(name, True, ivec3(255))
    #     textpos = text.get_rect()
    #     textpos.x = 0
    #     textpos.y = self.menu_sz // 2
    #     self.screen.surface.blit(text, textpos)
        return True

    def draw(self):
        self.gui.draw_ui(self.screen.surface)
        self.screen.render()
        pygame.display.flip()
        # self.root.update_idletasks()
        # self.root.update()

    def __call__(self):
        try:
            self.done = False
            while not self.done:
                try:
                    dt = self.clock.tick(self.options.fps) / 1000.0
                except:
                    self.deinit()
                    break
                self.logic(dt)
                if self.done:
                    break
                self.render()
                self.draw()
        except:
            print(traceback.format_exc())

        self.deinit()

        return 0

    def deinit(self):
        for lp in self.launchpads:
            if lp.out:
                lp.out.Reset()
                lp.out.LedSetMode(0)
        for out in self.out:
            out.close()
            out.abort()
        self.out = []

