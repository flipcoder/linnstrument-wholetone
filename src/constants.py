from glm import ivec2, vec2, ivec3, vec3

TITLE = "midimech"
# FOCUS = False
#U+1D12C flat
#1D130 sharp
NOTES_SHARPS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOTES_FLATS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
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
