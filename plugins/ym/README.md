# Audacious YM input plugin

Native Audacious 4.6.1 input plugin for Atari ST YM2149 music. It uses the
vendored ST-Sound implementation and supports YM5/YM6 plus LHa `-lh5-`
containers handled by ST-Sound itself.

Build with `./build.sh`. This produces `ym.so` and the independent
`test_stsound` renderer. To install for a user-managed Audacious setup, copy
`ym.so` into that setup's Audacious input-plugin directory, then restart
Audacious. This project intentionally does not install it automatically.

Playback is 44.1 kHz signed 16-bit stereo. ST-Sound renders mono samples; the
plugin duplicates each sample to both channels. Looping is explicitly disabled,
so a song ends naturally. Seeking is used when ST-Sound marks the loaded file
seekable. There are no subtunes and no plugin-side volume handling; Audacious's
output stage controls volume.

Run `./test_stsound input.ym output.wav`; it renders up to 30 seconds, writes a
stereo WAV, reports duration, and fails if RMS is at most 0.001.
