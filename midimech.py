#!/usr/bin/python3
# from tkinter import *
from collections import OrderedDict
from configparser import ConfigParser
import os, sys, glm, copy, binascii, struct, math, traceback, signal
import rtmidi2
from util import *
from dataclasses import dataclass
from glm import ivec2, vec2, ivec3, vec3
import time

with open(os.devnull, "w") as devnull:
    # suppress pygame messages
    stdout = sys.stdout
    sys.stdout = devnull
    import pygame, pygame.midi, pygame.gfxdraw

    sys.stdout = stdout
import pygame_gui

def error(msg):
    print(msg)
    pymsgbox.alert(msg)
    sys.exit(1)

try:
    import pymsgbox
except ImportError:
    print("The project dependencies have changed! Run the requirements setup command again!")
    sys.exit(1)

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
    pymsgbox.alert("The project dependencies have changed! Run the requirements setup command again!")
    sys.exit(1)

TITLE = "midimech"
# FOCUS = False
NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
WHOLETONE = True
FONT_SZ = 32
BRIGHTNESS = 0.4
C_COLOR = ivec3(0, 128 * BRIGHTNESS, 0)
YELLOW = ivec3(205 * BRIGHTNESS, 127 * BRIGHTNESS, 0)
LIGHT = ivec3(0, 0, 128 * BRIGHTNESS)
FGAB = ivec3(64 * BRIGHTNESS)
GRAY = ivec3(16 * BRIGHTNESS)
BORDER_COLOR = ivec3(48)
DARK = ivec3(0)
BASE_OFFSET = -4 # linnstrument
# CHORD_ANALYZER = get_option(opts,'chord_analyzer',False)
EPSILON = 0.0001
FADE_SPEED = 4.0

COLOR_CODES = [
    ivec3(0),  # default color
    ivec3(255, 0, 0),  # red
    ivec3(205, 205, 0),  # yellow
    ivec3(0, 127, 0),  # green
    ivec3(0, 127, 127),  # cyan
    ivec3(0, 0, 128),  # blue
    ivec3(159, 43, 104), # purple
    ivec3(0),  # off
    ivec3(80, 80, 80),  # gray
    ivec3(255, 127, 0),  # orange
    ivec3(0, 255, 0),  # lime
    ivec3(255, 127, 127),  # pink
]

# NOTE_COLORS = [
#     ivec3(255, 0, 0), # C
#     ivec3(255/2, 0, 0), # C#
#     ivec3(255, 127, 0), # D
#     ivec3(255/2, 127/2, 0), # D#
#     ivec3(255, 255, 0), # E
#     ivec3(0, 255, 0), # F
#     ivec3(0, 255/2, 0), # F#
#     ivec3(0, 0, 255), # G
#     ivec3(0, 0, 255/2), # G#
#     ivec3(128, 0, 128), # A
#     ivec3(128/2, 0, 128/2), # A#
#     ivec3(255, 0, 255) # B
# ]

# def invert_color(col): # ivec 255
#     r = vec3(col) / 255.0
#     for i in range(3):
#         r[i] = 1.0 - r[i]
#         r[i] *= 255
#     return ivec3(r)

def decompose_pitch_bend(pitch_bend_bytes):
    pitch_bend_value = (pitch_bend_bytes[1] << 7) + pitch_bend_bytes[0]
    pitch_bend_norm = (pitch_bend_value - 8192) / 8192.0
    return pitch_bend_norm


def compose_pitch_bend(pitch_bend_norm):
    pitch_bend_value = int((pitch_bend_norm + 1.0) * 8192)
    pitch_bend_bytes = [pitch_bend_value & 0x7F, (pitch_bend_value >> 7) & 0x7F]
    return pitch_bend_bytes

def decode_value(value):
    lsb = value & 0x7F
    msb = (value >> 7) & 0x7F
    return msb, lsb

# def pitch_bend_to_semitones(pitch_bend_value):
#     return bend_semitones

class Note:
    def __init__(self):
        # self.bend = 0.0
        # self.pressed = False
        # self.intensity = 0.0  # how much to light marker up (in app)
        self.pressure = 0.0  # how much the note is being pressed
        # self.dirty = False
        self.location = None  # on board
        self.midinote = None
        self.split = 0
        self.note = None

    # def logic(self, dt):
    #     if self.pressed:  # pressed, fade to pressure value
    #         if self.intensity != self.pressure:
    #             self.dirty = True
    #             if self.intensity < self.pressure:
    #                 self.intensity = min(pressure, self.intensity + dt * FADE_SPEED)
    #             else:
    #                 self.intensity = max(pressure, self.intensity - dt * FADE_SPEED)
    #     else:  # not pressed, fade out
    #         if self.intensity > 0.0:
    #             self.dirty = True
    #             self.pressure = 0.0
    #             self.intensity = max(0.0, self.intensity - dt * FADE_SPEED)


@dataclass
class DeviceSettings:
    row_offset: int
    octave: int
    transpose: int
    bend: int

@dataclass
class Options:
    version: int = 0
    lights: str = "4,7,3,7,3,3,7,3,7,3,7,3"
    split_lights: str = "4,7,5,7,5,5,7,5,7,5,7,5"
    one_channel: bool = False
    lite: bool = False # lite mode (no gfx)
    velocity_curve: float = 1.0
    velocity_curve_low: float = 0.5
    velocity_curve_high: float = 3.0
    min_velocity: float = 0
    max_velocity: float = 127
    show_lowest_note: bool = False
    mpe: bool = True
    hardware_split: bool = False
    midi_out: str = "midimech"
    split_out: str = "split"
    fps: int = 60
    split: bool = False
    foot_in: str = ""
    sustain: float = 1.0
    sustain_split: str = "both"
    size: int = 128
    width: int = 16
    height: int = 8

DEFAULT_OPTIONS = Options()


class Core:

    def rotate_mode(self, notes, mode):
        notes = copy.copy(notes)
        while mode:
            if notes[0] == 'x':
                notes = notes[1:] + notes[0]
            while notes[0] == '.':
                notes = notes[1:] + notes[0]
            mode -= 1
        return notes

    def prev_mode(self, ofs=1):
        self.next_mode(-ofs)

    def next_mode(self, ofs=1):
        self.set_mode((self.mode_index + ofs) % self.scale_notes.count('x'))

    def prev_scale(self, ofs=1):
        self.next_scale(-ofs)

    def next_scale(self, ofs=1):
        self.scale_index = (self.scale_index + ofs) % len(self.scale_db)
        self.scale_name = self.scale_db[self.scale_index]['name']
        self.set_mode(0)
    
    def set_mode(self, mode):
        self.scale_notes = self.rotate_mode(self.scale_db[self.scale_index]['notes'], mode)
        self.mode_index = mode
        try:
            self.mode_name = self.scale_db[self.scale_index]['modes'][mode]
        except:
            self.mode_name = 'Mode ' + str(self.mode_index + 1)
        self.scale_root = mode

    def set_scale(self, scale, mode):
        self.scale_index = scale
        self.scale_name = self.scale_db[scale]['name']
        self.set_mode(mode)
    
    def init_hardware(self):
        pass

    def has_velocity_curve(self):
        return abs(self.velocity_curve_ - 1.0) > EPSILON

    def has_velocity_settings(self):
        return (
            self.options.min_velocity > 0
            or self.options.max_velocity < 127
            or self.has_velocity_curve()
        )

    def velocity_curve(self, val):  # 0-1
        if self.has_velocity_curve():
            val = val**self.velocity_curve_
        return val

    def send_cc(self, channel, cc, val):
        if not self.linn_out:
            return
        # msg = [0xb0 | channel, cc, val]
        self.linn_out.send_cc(channel, cc, val)
        # self.linn_out.send_messages(0xb0, [(channel, cc, val)])

    def set_light(self, x, y, col):  # col is [1,11], 0 resets
        if y < 0 or y > self.board_h:
            return
        if x < 0 or x > self.board_w:
            return

        self.red_lights[y][x] = (col == 1)
        if self.linn_out:
            self.send_cc(0, 20, x + 1)
            self.send_cc(0, 21, self.board_h - y - 1)
            self.send_cc(0, 22, col)

        if self.launchpad:
            lp_col = COLOR_CODES[col]
            if 0 <= x < 8 and 0 <= y < 8:
                self.launchpad.LedCtrlXY(x, y+1, lp_col[0], lp_col[1], lp_col[2])

    def reset_light(self, x, y, reset_red=True):
        note = self.get_note_index(x, y) % 12
        if self.is_split():
            split_chan = self.channel_from_split(x, self.board_h - y - 1)
            if split_chan:
                light_col = self.options.split_lights[note]
                if self.scale:
                    try:
                        light_col = light_col if self.scale_notes[note]!='.' else 7
                    except IndexError:
                        light_col = 7
            else:
                light_col = self.options.lights[note]
                if self.scale:
                    try:
                        light_col = light_col if self.scale_notes[note]!='.' else 7
                    except IndexError:
                        light_col = 7
        else:
            light_col = self.options.lights[note]
            if self.scale:
                try:
                    light_col = light_col if self.scale_notes[note]!='.' else 7
                except IndexError:
                    light_col = 7

        self.set_light(x, y, light_col)
        self.red_lights[y][x] = False

    def reset_launchpad_light(self, x, y):
        note = self.get_note_index(x, 8-y-1) % 12
        # if self.is_split():
        #     split_chan = self.channel_from_split(x, self.board_h - y - 1)
        #     if split_chan:
        #         light_col = self.options.split_lights[note]
        #     else:
        light_col = self.options.lights[note]
        # else:
        #     light_col = self.options.lights[note]
        self.set_launchpad_light(x, y, light_col)

    def set_red_light(self, x, y, state=True):
        self.red_lights[y][x] = state
        if self.launchpad:
            lp_col = ivec3(127, 0, 0)
            if state:
                self.launchpad.LedCtrlXY(x, y, lp_col[0], lp_col[1], lp_col[2])

    def set_launchpad_light(self, x, y, color):
        col = COLOR_CODES[color]
        self.launchpad.LedCtrlXY(x, 8-y, col[0], col[1], col[2])

    def setup_lights(self):
        for y in range(self.board_h):
            for x in range(self.board_w):
                if self.red_lights[y][x]:
                    self.set_light(x, y, 1)
                    self.set_red_light(x, y, True)
                else:
                    self.reset_light(x, y)

    def reset_lights(self):
        for y in range(self.board_h):
            for x in range(self.board_w):
                self.set_light(x, y, 0)

    def get_octave(self, x, y):
        try:
            return self.octaves[y - self.board_h + self.flipped][x] + self.octave
        except IndexError:
            pass

    def xy_to_midi(self, x, y):
        row = self.board_h - y
        r = x % self.board_w + 25.5 + 2.5 * row  # FIXME: make this simpler
        r *= 2
        r = int(r)
        r += (self.octave + self.octave_base) * 12
        r += self.transpose * 2
        if self.flipped:
            r += 7
        return r

    def get_note_index(self, x, y):
        y += self.flipped
        x += self.transpose
        ofs = (self.board_h - y) // 2 + BASE_OFFSET
        step = 2 if WHOLETONE else 1
        if y % 2 == 1:
            return ((x - ofs) * step) % len(NOTES)
        else:
            return ((x - ofs) * step + 7) % len(NOTES)

    def get_note(self, x, y):
        return NOTES[self.get_note_index(x, y)]

    def get_color(self, x, y):
        # return NOTE_COLORS[get_note_index(x, y)]
        note = self.get_note_index(x, y)
        if self.is_split():
            split_chan = self.channel_from_split(x, self.board_h - y - 1)
            if split_chan:
                light_col = self.options.split_lights[note]
                if self.scale:
                    try:
                        light_col = light_col if self.scale_notes[note]!='.' else 7
                    except IndexError:
                        light_col = 7
            else:
                light_col = self.options.lights[note]
                if self.scale:
                    try:
                        light_col = light_col if self.scale_notes[note]!='.' else 7
                    except IndexError:
                        light_col = 7

        else:
            light_col = self.options.lights[note]
            if self.scale:
                try:
                    light_col = light_col if self.scale_notes[note]!='.' else 7
                except IndexError:
                    light_col = 7

        return COLOR_CODES[light_col]

    def mouse_held(self):
        return self.mouse_midi != -1

    # layout button x, y and velocity
    def mouse_pos_to_press(self, x, y):
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
        data = [0x90 if state else 0x80, midinote, vel]
        if self.midi_out:
            self.midi_write(self.midi_out, data, 0)

    def mouse_hold(self, x, y):
        return self.mouse_press(x, y, True, hold=True)

    def mouse_release(self, x=None, y=None):
        # x and y provided? it's a specific coordinate
        if x is not None and y is not None:
            return self.mouse_press(x, y, False)
        # x and y not provided? it uses the primary mouse coordinate
        if self.mouse_midi != -1:
            self.mark_xy(self.mouse_mark.x, self.mouse_mark.y, False)
            data = [0x80, self.mouse_midi, 127]
            if self.midi_out:
                self.midi_write(self.midi_out, data, 0)
            self.mouse_midi = -1

    def mouse_hover(self, x, y):
        self.mouse_press(x, y, hover=True)

    # Given an x,y position, find the octave
    #  (used to initialize octaves 2D array)
    def init_octave(self, x, y):
        return int((x + 4 + self.transpose + y * 2.5) // 6)

    def init_board(self):
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
        self.octaves = []
        for y in range(self.board_h + 1):  # 1 = flipping
            self.octaves.append([])
            for x in range(self.max_width):
                self.octaves[y].append(self.init_octave(x, y))
        self.octaves = list(reversed(self.octaves))

        self.notes = [None] * 16  # polyphony
        for i, note in enumerate(self.notes):
            self.notes[i] = Note()

        self.chord_notes = [False] * 12

    def midi_write(self, dev, msg, ts=0):
        if dev:
            dev.send_raw(*msg)

    def next_free_note(self):
        for note in self.notes:
            if note.location is None:
                return note
        return None

    def note_on(self, data, timestamp, width=None, curve=True, mpe=None):
        if mpe is None:
            mpe = self.options.mpe
        d0 = data[0]
        # print(data)
        ch = d0 & 0x0F
        msg = (data[0] & 0xF0) >> 4
        aftertouch = (msg == 10)
        if self.options.one_channel:
            data[0] = d0 & 0xF0  # send all to channel 0 if enabled
        row = None
        col = None

        within_hardware_split = False
        if width is None:
            if self.options.hardware_split:
                if self.board_w == 25: # 200
                    left_width = 11
                    right_width = 14
                    if ch >= 8:
                        width = right_width
                        within_hardware_split = True
                    else:
                        width = left_width
                else:
                    left_width = 8
                    right_width = 8
                    if ch >= 8:
                        width = right_width
                        within_hardware_split = True
                    else:
                        width = left_width
            else:
                width = self.board_w
            # else: # 128
                # width = 8 if self.options.hardware_split else 16
        
        if self.options.debug:
            print("MIDI:", data)
            print("Message:", msg)
            print("Channel:", ch)
            print("---")

        if mpe:
            row = data[1] // width
            col = data[1] % width
            if within_hardware_split:
                data[1] += left_width
            data[1] = col + 30 + 2.5 * row
            data[1] *= 2
            data[1] = int(data[1])
            if within_hardware_split:
                data[1] += left_width * 2
            # print(data[1])
        else:
            row = ch % 8
            col = ch // 8
            data[1] *= 2
            try:
                data[1] -= row * 5
            except IndexError:
                pass
        
        data[1] += (self.octave + self.octave_base) * 12
        data[1] += BASE_OFFSET
        midinote = data[1] - 24 + self.transpose * 2
        split_chan = 0
        if self.is_split():
            split_chan = self.channel_from_split(col, row)
        if not aftertouch:
            self.mark(midinote, 1, only_row=row)
        data[1] += self.out_octave * 12 + self.transpose * 2
        if self.flipped:
            data[1] += 7
        
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
            if self.options.mpe:
                note = self.notes[ch]
            else:
                note = self.next_free_note()
            if note:
                if note.location is None:
                    note.location = ivec2(0)
                note.location.x = col
                note.location.y = row
                note.pressure = vel
                note.midinote = data[1]
                note.split = split_chan

        self.chord_notes[data[1]%12] = True
        self.dirty_chord = True

        if self.is_split():
            if split_chan == 0:
                # self.midi_out.write([[data, ev[1]]]
                self.midi_write(self.midi_out, data, timestamp)
            else:
                self.midi_write(self.split_out, data, timestamp)
        else:
            self.midi_write(self.midi_out, data, timestamp)

    def note_off(self, data, timestamp, width=None, mpe=None):
        if mpe is None:
            mpe = self.options.mpe
        
        d0 = data[0]
        # print(data)
        ch = d0 & 0x0F
        msg = (data[0] & 0xF0) >> 4
        if self.options.one_channel:
            data[0] = d0 & 0xF0  # send all to channel 0 if enabled
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
                if self.board_w == 25: # 200
                    left_width = 11
                    right_width = 14
                    if ch >= 8:
                        width = right_width
                        within_hardware_split = True
                    else:
                        width = left_width
                else:
                    left_width = 8
                    right_width = 8
                    if ch >= 8:
                        width = right_width
                        within_hardware_split = True
                    else:
                        width = left_width
            else:
                width = self.board_w
        
        if not mpe:
            row = ch % 8
            col = ch // 8
        if mpe:
            # row and col within the current split
            # row = data[1] // width
            # col = data[1] % width
            # print(data[1])
            # # data[1] = data[1] % width + 30 + 2.5 * row
            # data[1] *= 2
            # data[1] = int(data[1])
            # if self.options.hardware_split and ch >= 8:
            #     data[1] += self.board_w
            row = data[1] // width
            col = data[1] % width
            if within_hardware_split:
                data[1] += left_width
            data[1] = col + 30 + 2.5 * row
            data[1] *= 2
            data[1] = int(data[1])
            if within_hardware_split:
                data[1] += left_width * 2
        else:
            data[1] *= 2
            try:
                data[1] -= row * 5
            except IndexError:
                pass
        
        data[1] += (self.octave + self.octave_base) * 12
        data[1] += BASE_OFFSET
        midinote = data[1] - 24 + self.transpose * 2
        if self.is_split():
            split_chan = self.channel_from_split(col, row)
        self.mark(midinote, 0, only_row=row)
        data[1] += self.out_octave * 12 + self.transpose * 2
        if self.flipped:
            data[1] += 7

        self.chord_notes[data[1]%12] = False
        self.dirty_chord = True

        if self.is_split():
            if split_chan == 0:
                self.midi_write(self.midi_out, data, timestamp)
            else:
                self.midi_write(self.split_out, data, timestamp)
        else:
            self.midi_write(self.midi_out, data, timestamp)
        # print('note off: ', data)

    def device_to_xy(self, data):
        mpe = self.options.mpe
        
        d0 = data[0]
        ch = d0 & 0x0F
        msg = (data[0] & 0xF0) >> 4
        if self.options.one_channel:
            data[0] = d0 & 0xF0  # send all to channel 0 if enabled
        row = None
        col = None

        within_hardware_split = False
        if self.options.hardware_split:
            if self.board_w == 25: # 200
                left_width = 11
                right_width = 14
                if ch >= 8:
                    width = right_width
                    within_hardware_split = True
                else:
                    width = left_width
            else:
                left_width = 8
                right_width = 8
                if ch >= 8:
                    width = right_width
                    within_hardware_split = True
                else:
                    width = left_width
        else:
            width = self.board_w
        
        if not mpe:
            row = ch % 8
            col = ch // 8
        if mpe:
            row = data[1] // width
            col = data[1] % width
            if within_hardware_split:
                data[1] += left_width
            data[1] = col + 30 + 2.5 * row
            data[1] *= 2
            data[1] = int(data[1])
            if within_hardware_split:
                data[1] += left_width * 2
        else:
            data[1] *= 2
            try:
                data[1] -= row * 5
            except IndexError:
                pass
        
        return col, row
    
    def cb_midi_in(self, data, timestamp):
        # d4 = None
        # if len(data)==4:
        #     d4 = data[3]
        #     data = data[:3]
        d0 = data[0]
        # print(data)
        ch = d0 & 0x0F
        msg = (data[0] & 0xF0) >> 4
        if self.options.one_channel:
            data[0] = d0 & 0xF0  # send all to channel 0 if enabled
        row = None
        col = None
        if not self.options.mpe:
            row = ch % 8
            col = ch // 8
        if msg == 9:  # note on
            if data[2] == 0: # 0 vel
                self.note_off(data, timestamp)
            else:
                self.note_on(data, timestamp)
            # print('note on: ', data)
        elif msg == 8:  # note off
            self.note_off(data, timestamp)
        elif 0xF0 <= msg <= 0xF7:  # sysex
            self.midi_write(self.midi_out, data, timestamp)
        else:
            # pitch bend
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
            
            if skip:
                pass
            elif msg == 11 and data[1] == 64:  # sustain pedal
                if self.is_split():
                    for dev in self.sustainable_devices():
                        self.midi_write(dev, data, timestamp)
                else:
                    self.midi_write(self.midi_out, data, timestamp)
            elif self.is_split(): # everything else (if split)...
                note = self.notes[ch]
                if ch == 0:
                    self.midi_write(self.midi_out, data, timestamp)
                    self.midi_write(self.split_out, data, timestamp)
                elif note.location is not None:
                    col = self.notes[ch].location.x
                    row = self.notes[ch].location.y
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
        # print(msg, timestamp)
        ch = data[0] & 0x0F
        msg = data[0] >> 4
        if msg == 9:  # note on
            self.mark(data[1] + self.vis_octave * 12, 1, True)
        elif msg == 8:  # note off
            self.mark(data[1] + self.vis_octave * 12, 0, True)

    def cb_foot(self, data, timestamp):
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

    # uses button state events (mk3 pro)
    def cb_launchpad_in(self, event, timestamp=0):
        # if (self.launchpad_mode == "pro" or self.launchpad_mode == "promk3") and event[0] == 255:
        # if event[0] >= 255:
        #     # I'm testing the mk3 method on an lpx, so I'll check this here
        #     vel = event[2] if self.launchpad_mode == 'lpx' else event[1]
        #     for note in self.notes:
        #         if note.location:
        #             print(note.midinote)
        #             self.note_on([160, note.midinote, vel], timestamp, width=8, mpe=True)
        
        if self.launchpad_mode == 'lpx' and event[0] >= 255: # pressure
            x = event[0] - 255
            y = 8 - (event[1] - 255)
            vel = event[2]
            note = y * 8 + x
            self.note_on([160, note, event[2]], timestamp, width=8, mpe=True)
        elif event[2] == 0: # note off
            x = event[0]
            y = 8 - event[1]
            if 0 <= x < 8 and 0 <= y < 8:
                note = y * 8 + x
                self.reset_launchpad_light(x, y)
                self.note_off([128, note, event[2]], timestamp, width=8, mpe=True)
        else: # note on
            x = event[0]
            y = 8 - event[1]
            if 0 <= x < 8 and 0 <= y < 8:
                note = y * 8 + x
                self.set_launchpad_light(x, y, 1) # red
                self.note_on([144, note, event[2]], timestamp, width=8, mpe=True)
            else:
                if self.launchpad_mode == 'lpx':
                    if x == 0:
                        self.octave += 1
                        self.dirty = self.dirty_lights = True
                        self.clear_marks(use_lights=False)
                    elif x == 1:
                        self.octave -= 1
                        self.dirty = self.dirty_lights = True
                        self.clear_marks(use_lights=False)
                    elif x == 2:
                        self.transpose_board(-1)
                        self.dirty = self.dirty_lights = True
                    elif x == 3:
                        self.transpose_board(1)
                        self.dirty = self.dirty_lights = True

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
    #             self.transpose_board(-1)
    #             self.dirty = self.dirty_lights = True
    #         elif event == [176, 94, 127, 0]:
    #             self.transpose_board(1)
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
        self.quit()

    def __init__(self):
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
        for scale in self.scale_db:
            notes = scale['notes']
            count = notes.count('x')
            dupes = (scale.get('duplicates') is True) or False
            if not dupes:
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

        # print(self.scale_db)

        self.options = Options()

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

        if len(self.options.lights) != 12:
            pymsgbox.alert("Invalid light color configuration. Make sure you have 12 light colors under the lights option or remove it.")
            sys.exit(1)
        if len(self.options.split_lights) != 12:
            pymsgbox.alert("Invalid light color configuration for split. Make sure you have 12 light colors under the split_lights option or remove it.")
            sys.exit(1)

        self.options.one_channel = get_option(
            opts, "one_channel", DEFAULT_OPTIONS.one_channel
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

        self.options.min_velocity = get_option(
            opts, "min_velocity", DEFAULT_OPTIONS.min_velocity
        )
        self.options.max_velocity = get_option(
            opts, "max_velocity", DEFAULT_OPTIONS.max_velocity
        )
        self.options.show_lowest_note = get_option(
            opts, "show_lowest_note", DEFAULT_OPTIONS.show_lowest_note
        )
        # self.options.mpe = get_option(
        #     opts, "mpe", DEFAULT_OPTIONS.mpe
        # ) or get_option(
        #     opts, "no_overlap", DEFAULT_OPTIONS.mpe
        # )
        self.options.midi_out = get_option(opts, "midi_out", DEFAULT_OPTIONS.midi_out)
        self.options.split_out = get_option(
            opts, "split_out", DEFAULT_OPTIONS.split_out
        )
        self.options.fps = get_option(opts, "fps", DEFAULT_OPTIONS.fps)
        self.split_state = self.options.split = get_option(
            opts, "split", DEFAULT_OPTIONS.split
        )
        self.options.foot_in = get_option(opts, "foot_in", DEFAULT_OPTIONS.foot_in)
        self.options.sustain = get_option(
            opts, "sustain", DEFAULT_OPTIONS.sustain
        )  # sustain scale

        # which split the sustain affects
        self.options.sustain_split = get_option(
            opts, "sustain_split", "both"
        )  # left, right, both
        if self.options.sustain_split not in ("left", "right", "both"):
            print("Invalid sustain split value. Options: left, right, both.")
            sys.exit(1)

        self.options.size = get_option(opts, "size", DEFAULT_OPTIONS.size)
        if self.options.size == 128:
            self.options.width = 16
        elif self.options.size == 200:
            self.options.width = 25
            self.options.hardware_split = True

        self.options.launchpad = get_option(opts, 'launchpad', True)
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
        self.transpose = 0
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
            relative_rect=pygame.Rect((bs.x * 2 + 2, y), bs),
            text="<MOV",
            manager=self.gui,
        )
        self.btn_transpose_up = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 3 + 2, y), bs),
            text="MOV>",
            manager=self.gui,
        )
        # self.btn_size = pygame_gui.elements.UIButton(
        #     relative_rect=pygame.Rect((bs.x * 4 + 2, y), bs),
        #     text="SIZE",
        #     manager=self.gui,
        # )
        self.btn_rotate = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 4 + 2, y), bs),
            text="ROT",
            manager=self.gui,
        )
        self.btn_flip = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 5 + 2, y), bs),
            text="FLIP",
            manager=self.gui,
        )

        if self.options.mpe:  # split only works with no overlap for now
            self.btn_split = pygame_gui.elements.UIButton(
                relative_rect=pygame.Rect((bs.x * 6 + 2, y), (bs.x * 2, bs.y)),
                text="SPLIT: " + ("ON" if self.split_state else "OFF"),
                manager=self.gui,
            )

        # if self.options.experimental:
        self.btn_prev_scale = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 8 + 2, y), (bs.x, bs.y)),
            text='<SCL',
            manager=self.gui
        )
        self.btn_next_scale = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 9 + 2, y), (bs.x, bs.y)),
            text='SCL>',
            manager=self.gui
        )

        self.btn_prev_mode = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 10 + 2, y), (bs.x, bs.y)),
            text='<MOD',
            manager=self.gui
        )
        self.btn_next_mode = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect((bs.x * 11 + 2, y), (bs.x, bs.y)),
            text='MOD>',
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

        outnames = rtmidi2.get_out_ports()
        for i in range(len(outnames)):
            name = outnames[i]
            name_lower = name.lower()
            # print(name_lower)
            if "linnstrument" in name_lower:
                print("Instrument (Out): " + name)
                self.linn_out = rtmidi2.MidiOut()
                self.linn_out.open_port(i)
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
        self.launchpad = None
        self.launchpad_mode = None

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

        if self.options.launchpad:
            lp = None
            if self.options.experimental:
                lp = launchpad.LaunchpadPro()
                if lp.Check(0):
                    if lp.Open(0):
                        self.launchpad_mode = "pro"
            if launchpad.LaunchpadProMk3().Check(0):
                lp = launchpad.LaunchpadProMk3()
                if lp.Open(0):
                    self.launchpad_mode = "promk3"
            if not self.launchpad_mode:
                if launchpad.LaunchpadLPX().Check(1):
                    lp = launchpad.LaunchpadLPX()
                    if lp.Open(1):
                        self.launchpad_mode = "lpx"
                    lp.LedCtrlXY(0, 0, 0, 0, 63)
                    lp.LedCtrlXY(1, 0, 0, 0, 63)
                    lp.LedCtrlXY(2, 0, 63, 0, 63)
                    lp.LedCtrlXY(3, 0, 63, 0, 63)
            if self.launchpad_mode is not None:
                self.launchpad = lp

        self.done = False
        
        if not self.midi_out:
            pymsgbox.alert(
                "No MIDI output device detected.  Install a midi loopback device and name it 'midimech'!", "Midimech"
            )
            sys.exit(1)

        self.dirty = True
        self.dirty_lights = True
        self.dirty_chord = False

        w = self.max_width
        h = self.board_h
        self.board = [[0 for x in range(w)] for y in range(h)]
        self.red_lights = [[False for x in range(w)] for y in range(h)]
        self.launchpad_state = [[None for x in range(8)] for y in range(8)]

        self.font = pygame.font.Font(None, FONT_SZ)

        # self.retro_font = pygame.font.Font("PressStart2P.ttf", FONT_SZ)
        self.clock = pygame.time.Clock()

        self.init_hardware()

        # if transpose_board:
        #     self.transpose_board(transpose_board)

        # self.setup_lights()

        self.setup_rpn()
        # self.test()

    def setup_rpn(self, on=True):
        if on:
            if self.options.mpe:
                self.mpe_rpn()
                self.transpose_rpn()
            else:
                self.rows_rpn()
            self.bend_rpn()
            self.split_rpn(self.options.hardware_split)
        else:
            self.transpose_rpn(False)
            self.mpe_rpn(False)
            self.bend_rpn(False)
            self.split_rpn(False)
            self.split_rpn(False)

    def split_rpn(self, on=True):
        if self.options.hardware_split:
            self.rpn(200, 1 if on else 0)

            self.send_cc(0, 20, 0)
            self.send_cc(0, 21, 1)
            self.send_cc(0, 22, 7 if on else 0)
        else:
            self.rpn(200, 7)

    def rpn(self, num, value):
        num_msb, num_lsb = decode_value(num)
        value_msb, value_lsb = decode_value(value)
        self.midi_write(self.linn_out, [176, 99, num_msb])
        self.midi_write(self.linn_out, [176, 98, num_lsb])
        self.midi_write(self.linn_out, [176, 6, value_msb])
        self.midi_write(self.linn_out, [176, 38, value_lsb])
        self.midi_write(self.linn_out, [176, 101, 127])
        self.midi_write(self.linn_out, [176, 100, 127])
        time.sleep(0.1)

    def mpe_rpn(self, on=True):
        if on:
            self.rpn(0, 1)
            self.rpn(100, 1)
            self.rpn(227, 0)
        else:
            self.rpn(227, 5)

    def rows_rpn(self):
        self.rpn(0, 2)
        self.rpn(100, 2)

    def bend_rpn(self, on=True):
        if on:
            self.rpn(19, 24)
            self.rpn(119, 24)
        else:
            self.rpn(19, 48)
            self.rpn(119, 48)
    
    def transpose_rpn(self, on=True):
        if on:
            self.rpn(36, 2)
            self.rpn(37, 13)
            self.rpn(136, 2)
            self.rpn(137, 13)

            # turn transpose light off
            self.send_cc(0, 20, 0)
            self.send_cc(0, 21, 4)
            self.send_cc(0, 22, 7)

        else:
            self.rpn(36, 5)
            self.rpn(37, 7)
            self.rpn(136, 5)
            self.rpn(137, 7)

    # def test(self):
    #     self.transpose_rpn()

    def transpose_board(self, val):
        aval = abs(val)
        if aval > 1:  # more than one shift
            sval = sign(val)
            for rpt in range(aval):
                self.transpose_board(sval)
                self.transpose += sval
        elif val == 1:  # shift right (add column left)
            for y in range(len(self.board)):
                self.board[y] = [0] + self.board[y][:-1]
            self.transpose += val
        elif val == -1:  # shift left (add column right)
            for y in range(len(self.board)):
                self.board[y] = self.board[y][1:] + [0]
            self.transpose += val

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

    def mark_xy(self, x, y, state, use_lights=False):
        if self.flipped:
            y -= 1
        idx = self.get_note_index(x, y)
        octave = self.get_octave(x, y)
        try:
            self.board[y + self.flipped][x] = state
        except IndexError:
            print("mark_xy: Out of range")
            pass
        if use_lights:
            if state:
                self.set_light(x, y, 1)
            else:
                self.reset_light(x, y)
        self.dirty = True

    def mark(self, midinote, state, use_lights=False, only_row=None):
        if only_row is not None:
            only_row = self.board_h - only_row - 1 - self.flipped  # flip
            try:
                rows = [self.board[only_row]]
            except IndexError:
                rows = self.board
            y = only_row
        else:
            rows = self.board
            y = 0
        for row in rows:
            x = 0
            for x in range(len(row)):
                idx = self.get_note_index(x, y)
                # print(x, y, midinote%12, idx)
                if midinote % 12 == idx:
                    octave = self.get_octave(x, y)
                    if octave == midinote // 12:
                        self.board[y + self.flipped][x] = state
                        if use_lights:
                            if state:
                                self.set_light(x, y, 1)
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
        return self.options.mpe and self.split_state and self.split_out

    def logic(self, dt):
        # keys = pygame.key.get_pressed()

        if self.launchpad:
            # while True:
            #     events = self.launchpad.EventRaw()
            #     if events != []:
            #         for ev in events:
            #             self.cb_launchpad_in(ev[0], ev[1])
            #     else:
            #         break
            while True:
                event = self.launchpad.ButtonStateXY(returnPressure = True)
                if event:
                    self.cb_launchpad_in(event)
                else:
                    break
        
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.quit()
                break
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    self.quit()
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
                    elif ev.ui_element == self.btn_transpose_down:
                        self.transpose_board(-1)
                        self.dirty = self.dirty_lights = True
                        self.clear_marks(use_lights=False)
                    elif ev.ui_element == self.btn_transpose_up:
                        self.transpose_board(1)
                        self.dirty = self.dirty_lights = True
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
                            self.transpose += 3
                            self.rotated = False
                        else:
                            self.transpose -= 3
                            self.rotated = True
                        self.clear_marks(use_lights=False)
                        self.dirty = self.dirty_lights = True
                    elif ev.ui_element == self.btn_flip:
                        self.flipped = not self.flipped
                        self.clear_marks(use_lights=False)
                        self.dirty = self.dirty_lights = True
                    elif ev.ui_element == self.btn_split:
                        if self.split_out:
                            self.split_state = not self.split_state
                            self.btn_split.set_text(
                                "SPLIT: " + ("ON" if self.split_state else "OFF")
                            )
                            self.dirty = self.dirty_lights = True
                        else:
                            pymsgbox.alert("You need to add another MIDI loopback device called 'split'")
                    elif ev.ui_element == self.btn_next_scale:
                        self.next_scale()
                        self.dirty = self.dirty_lights = True
                    elif ev.ui_element == self.btn_prev_scale:
                        self.prev_scale()
                        self.dirty = self.dirty_lights = True
                    elif ev.ui_element == self.btn_next_mode:
                        self.next_mode()
                        self.dirty = self.dirty_lights = True
                    elif ev.ui_element == self.btn_prev_mode:
                        self.prev_mode()
                        self.dirty = self.dirty_lights = True
                # elif ev.type == pygame_gui.UI_HORIZONTAL_SLIDER_MOVED:
                #     if ev.ui_element == self.slider_velocity:
                #         global self.options.velocity_curve
                #         self.options.velocity_curve = ev.value
                #         self.config_save_timer = 1.0

                self.gui.process_events(ev)

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

        # TODO: if notes changed
        if self.dirty_chord:
            notes = set()
            for i, note in enumerate(self.chord_notes):
                if note:
                    notes.add(NOTES[i])
            if notes:
                self.chord = mp.alg.detect(mp.chord(','.join(notes)))
                try:
                    self.chord = self.chord[0:self.chord.index(' sort')]
                except ValueError:
                    pass
                if self.chord.startswith('note '):
                    self.chord = self.chord[len('note '):-1]
            else:
                self.chord = ''
            self.dirty_chord = False
            self.dirty = True
        
        if not self.options.lite:
            self.gui.update(dt)

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
                note = self.get_note(x, y)

                split_chan = self.channel_from_split(x, y)

                # note = str(self.get_octave(x, y)) # show octave
                # brightness = 1.0 if cell else 0.5

                col = None

                # if cell:
                #     col = ivec3(255,0,0)
                # else:
                #     col = self.get_color(x, y)
                lit_col = ivec3(255, 0, 0)
                unlit_col = copy.copy(self.get_color(x, y))
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

        # for note in self.notes:
        #     if note.location is None:
        #         continue
        #     print(note.location)

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
        if self.launchpad:
            self.launchpad.Reset()
            self.launchpad.LedSetMode(0)
        for out in self.out:
            out.close()
            out.abort()
        self.out = []


def main():
    core = None
    try:
        core = Core()
        core()
    except:
        print(traceback.format_exc())
    del core
    pygame.midi.quit()
    pygame.display.quit()
    os._exit(0)
    # pygame.quit()


if __name__ == "__main__":
    main()
