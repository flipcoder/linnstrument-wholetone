
# midimech

![midimech](https://i.imgur.com/iNKaTi3.png)

<a href="https://www.buymeacoffee.com/flipcoder" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/default-orange.png" alt="Buy Me A Coffee" height="41" width="174"></a>

**IN DEVELOPMENT**

Midimech is an alternative musical note layout system for the LinnStrument and LaunchPad X.  It uses a wholetone-based isomorphic layout.  I was surprised to find out this layout and its variants were not in common usage, despite being incredibly convincing.  This project intends to help popularize the layout and bring it to more people.

Midimech supports:
- Using the mech layout on LinnStrument and LaunchPad X
- Vibrato detection on LaunchPad X (wiggle your notes!)
- Bigger range than the default LinnStrument layout
- Synthesia/DAW visualization for learning songs
- Diagonal split
- Transposing and Octave shifting
- Chord Analyzer
- 130+ Scales/Modes
- Custom Lights
- Great for playing fast arpeggios and piano runs

**Please read the setup instructions and important notes before usage.  Have fun!**

License: MIT (see *Attributions*)

Copyright (c) 2023 Grady O'Connell

*This project is not affiliated with Roger Linn Design.*

LinnStrument Community Discord: https://discord.gg/h2BcrzmTXe

![Screenshot](https://i.imgur.com/v25g9NO.png)

## Video

[![Video](https://img.youtube.com/vi/GbkhwpPsbPo/0.jpg)](https://www.youtube.com/watch?v=GbkhwpPsbPo)

## Advantages

- Notes that sound good together are closer together.  Notes that sound worse are furthest apart.  Mistakes will be less likely and more obvious!
- Like the LinnStrument's layout, it is also isomorphic (the same chord and scale shapes can be played anywhere)
- The most common chords and scales are far easier to play and remember than other layouts.
- Extended range compared to standard +5 tuning, making room for using a split.
- Less finger stretching than other layouts when playing chords, which may help ergonomically.
- Arpeggios are quite smooth, as you're simply walking stacked shapes.

## Cheat Sheet

![Page 1](https://raw.githubusercontent.com/flipcoder/mech-theory/main/mech-cheatsheet-0.png)
![Page 2](https://raw.githubusercontent.com/flipcoder/mech-theory/main/mech-cheatsheet-1.png)

[View PDF](https://github.com/flipcoder/mech-theory/blob/main/mech-cheatsheet.pdf)

## What is the Mech Layout?

When I originally discovered this layout, I didn't yet have an isomorphic controller, so my friends and I would map it to my mechanical keyboard to play.  Because of this, we referred to it as "playing the mech".  After getting a LinnStrument and LaunchPad, I've continued using this name for the layout itself.  It could also be referred to as the "wholetone layout" or "grid-based Wicki-Hayden" but I still prefer calling it mech.

In the layout, each row consists of a whole tone scale separated by fourths.  The above cheat sheet document contains many common chord and scale shapes. 

The more you play, the more you'll notice it is much easier than other instrument layouts to learn and play, making it quite fun.  Its relation to the circle of 5ths makes certain music theory concepts easier to visualize and apply as well.

## Important Notes / Troubleshooting

So far, this has mostly been tested on the LinnStrument 128 and LaunchPad X.  If you own the LinnStrument 200, it might be less stable, so let me know if you run into any issues.  I'm saving up for a LinnStrument 200 so hit that donate button if you want to help out. :)

Midimech sends midi commands to your midi controller and does not replace the firmware of your device.  It changes certain settings for the program to function and resets them to common values after ending the program.

This program is *in development*, so some things may be buggy.  If a device persists in a different state after ending the program (such as if a crash occurs), try running the program again and closing it.  Otherwise try reconnecting or resetting your LinnStrument.

If you have issues with LinnStrument connectivity when the program starts, try recreating the virtual midi device before you start it.

That being said, I hope you enjoy it and have fun!

## Getting Started

### Windows

- [Download (Win)](https://github.com/zass30/midimech/releases)

After downloading, make sure to follow the instructions under `Setup`.

*Note: These builds are not always up to date.*

### Mac, Linux, and Running from Git

- Download the project by typing the following commands in terminal:
```
git clone https://github.com/zass30/midimech
```

- Switch to the new project folder:
```
cd midimech
```

- Install the dependencies:
```
pip3 install -r requirements.txt
```

- Follow the **Setup** instructions described in the section below.

- When running the program, you can use:
```
python3 midimech.py
```

### Setup

- First create a midi loopback device.  You can do this easily with LoopMidi on Windows or using "Audio MIDI Setup / MIDI Studio" on Mac.  Then set your DAW to use this device instead of the linnstrument.  Make sure the virtual device you set up has "midimech" in its device name, since this is how its detected by the program.

- If you're using the LinnStrument 200, set `size=200` in your settings.ini.  If you don't have a settings file, copy it from settings.ini.example.

- Run midimech.  You should see a window pop up with the layout.

- Your Linnstrument or LaunchPad X should show the colors of the layout and be playable in your DAW.

- To enable the split, create another midi loopback device called "split" and restart midimech.  Click the SPLIT button.  One side should turn blue.

## How to Play

### Scales
  
By default, the C major scale is colored.  You can highlight different notes by cycling the scale (SCL) and mode (MOD) buttons.  Notice how only the colors change, and not the note positions.

You can change the starting note of the scale by using the transpose (TR) buttons, as well as positioning the board using the move (MOV) buttons.

### Chords

Refer to the cheat sheet for a listing of many common chord shapes.

To play a chord, simply position the dotted black square of the chord on the note you want to play, and make the shape with your fingers.  For example a C major chord is made by playing the notes:

```
 G
C E
```

## Velocity Curve

You can modify the velocity curve using a decimal value.  Lower values are more sensitive.  The default is 1.0.

```
velocity_curve=0.5
```

You can also clamp the midi velocity value to a min (default: 0) and max (default: 127).

```
min_velocity=0
max_velocity=127
```

## Launchpad

Supported launchpads are automatically detected on program start.  Support for these will improve over time.

If you're on the LinnStrument and don't want your launchpad used, simply set it to false:
```
launchpad=false
```

### Vibrato

Midimech adds a cool feature to the Launchpad where it can detect wiggling a note to create a vibrato effect.  This is enabled by default and mapped to CC0.  If your synth supports CC0 vibrato, you should hear the vibrato activate by rocking your finger back and forth from left to right while pressing the note down.

You can disable it in settings.ini using:
```
vibrato=off
```

There is also experimental support for pitch wheel vibrato using:

```
vibrato=pitch
```

## Color Schemes

### LinnStrument Colors

LinnStrument colors can be changed in the settings using `lights` and `split_lights` for each split respectively.

```
lights=1,9,9,2,2,3,3,5,8,8,11,11
split_lights=4,7,5,7,5,5,7,5,7,5,7,5
```
The color numbers here are the values used by the LinnStrument.

### LaunchPad & App Colors

You can change the colors of the launchpad and in the app by setting `colors` and `split_colors` similarly as above.  This supports both hex values (starting with #) and common web color names.

```
colors=red,darkred,orange,goldenrod,yellow,green,darkolivegreen,blue,darkslateblue,indigo,darkorchid,pink
```

## Lite Mode (low GFX)

To activate lite mode, run midimech with `--lite` on the command line or set `lite=true` in your settings.

This disables extra graphics and chord analysis in the app to reduce latency on low end systems.

## One Channel Mode

MPE mode can be toggled in the app using the `MPE` button.

To send to a specific midi channel, set `one_channel` to the specific channel number.  The default is 0, which indicates using MPE.  Clicking `MPE` in the app toggles this between 0 (MPE) and 1 (first channel), otherwise the value in settings is used.

## Visualizer

### DAW visualization

Using this program, you can visualize the midi playing in your DAW on both the screen and LinnStrument.
You do this by creating another device in LoopMidi called "visualizer" then use a Midi Out plugin
on the track you want to visualize and set the plugin to use the visualizer midi device.

### Synthesia

To use the visualizer with Synthesia, create a new MIDI loopback device called "visualizer".
In Synthesia settings, set it as an output device for note lights.

## Future Plans

- Touchscreen support
- Find a way to adjust vibrato sensitivity without affecting slides.  Roger Linn has indicated that this is probably impossible, but I have a few ideas to try.
- Better velocity curve settings (right now its only basic options in the settings.ini).
- Better GUI and integration with the settings file.

## Attributions

This program is built using the following projects and libraries:

- [Pygame](https://github.com/pygame/pygame) and [Pygame-CE](https://github.com/pygame-community/pygame-ce)
- [Pygame_GUI](https://github.com/MyreMylar/pygame_gui)
- [RtMidi2](https://github.com/gesellkammer/rtmidi2)
- [PyGLM](https://github.com/Zuzu-Typ/PyGLM)
- [Launchpad-Py](https://github.com/FMMT666/launchpad.py) by FMMT666 ([CC Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/))
- [musicpy](https://github.com/Rainbow-Dreamer/musicpy) for Chord Analysis
- [webcolors](https://pypi.org/project/webcolors/)
- [pyyaml](https://pypi.org/project/PyYAML/)

Thank you!

## Contact / Questions

I'm on the LinnStrument Discord at https://discord.gg/h2BcrzmTXe.  Come hang out!

