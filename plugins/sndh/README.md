# SNDH input plugin for Audacious

This Audacious 4.6.1 `InputPlugin` plays Atari ST SNDH music through the
vendored sc68 library. It exposes SNDH subtunes, produces 44.1 kHz stereo S16
PCM, and does not loop playback.

Build it from this directory:

```sh
./build.sh
```

The build creates `sndh.so`. Install it into Audacious' input-plugin directory:

```sh
cp sndh.so /usr/lib/x86_64-linux-gnu/audacious/Input/
```

Check that `sndh.so` appears in Audacious' `plugin-registry`. Then kill any
running Audacious process so the bot watchdog starts a fresh instance and
Audacious registers the new plugin.
