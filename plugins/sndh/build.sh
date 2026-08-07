#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")" && pwd)
cd "$root"
vendor=vendor_sc68
build=build
rm -rf "$build"
mkdir -p "$build"/{file68,io68,emu68,libsc68}

if ! (cd "$vendor/as68" && ./configure && make); then
    # The trimmed vendor snapshot has an unexpanded SC68_PACKAGE() at the end
    # of configure.  Keep the prescribed configure/make attempt above, then
    # build this small host tool directly when that snapshot cannot configure.
    gcc -std=c17 -O2 -fcommon -DPACKAGE_VERSION='"2013.07.30"' \
        -DPACKAGE_URL='"http://sc68.atari.org"' \
        "$vendor/as68/as68.c" "$vendor/as68/error.c" \
        "$vendor/as68/expression.c" "$vendor/as68/opcode.c" "$vendor/as68/word.c" \
        -o "$vendor/as68/as68"
fi
"$vendor/as68/as68" --help >/dev/null
version_tweak=$(cd "$vendor" && tools/vcversion.sh)
sed -e 's/@VER_MAJOR@/3/' -e 's/@VER_MINOR@/0/' -e 's/@VER_PATCH@/0/' \
    -e "s/@VER_TWEAK@/$version_tweak/" "$vendor/libsc68/asm/version.s.in" \
    > "$vendor/libsc68/asm/version.s"
(cd "$vendor/libsc68" && ../as68/as68 asm/trapfunc.s -o trapfunc.bin >/dev/null)
hexdump -ve '1/1 "%d,\n"' "$vendor/libsc68/trapfunc.bin" > "$vendor/libsc68/sc68/trap68.h"
rm -f "$vendor/libsc68/trapfunc.bin"
# Equivalent to file68's configure substitution, with only zlib enabled.
sed 's/#undef FILE68_Z/#define FILE68_Z/' "$vendor/file68/sc68/file68_features.h.in" \
    > "$vendor/file68/sc68/file68_features.h"

# The vendored libraries normally obtain these from config.h.  They are kept
# deliberately out of autotools here, so provide the portable Linux results.
cflags=(-std=c17 -O2 -Wall -Wextra -Wpedantic -fPIC -D_DEFAULT_SOURCE -DHAVE_ASSERT_H -DHAVE_STDINT_H -DHAVE_STDLIB_H
    -DHAVE_STRING_H -DHAVE_STRINGS_H -DHAVE_UNISTD_H -DHAVE_FCNTL_H -DHAVE_SYS_STAT_H
    -DHAVE_SYS_TYPES_H -DHAVE_GETENV -DHAVE_STRDUP
    '-DPACKAGE_STRING="sc68 3.0.0"' '-DPACKAGE_URL="http://sc68.atari.org"')

compile_archive() {
    local archive=$1 object_dir=$2 includes=$3
    shift 3
    local source object
    for source in "$@"; do
        object="$object_dir/$(basename "${source%.c}").o"
        gcc "${cflags[@]}" $includes -c "$source" -o "$object"
    done
    ar rcs "$archive" "$object_dir"/*.o
}

# Optional libao and libcurl backends are not needed by an Audacious input plugin.
file68_sources=(
    "$vendor/file68/src/error68.c" "$vendor/file68/src/file68.c" "$vendor/file68/src/gzip68.c"
    "$vendor/file68/src/ice68.c" "$vendor/file68/src/init68.c" "$vendor/file68/src/vfs68.c"
    "$vendor/file68/src/vfs68_ao.c" "$vendor/file68/src/vfs68_curl.c" "$vendor/file68/src/vfs68_fd.c" "$vendor/file68/src/vfs68_file.c"
    "$vendor/file68/src/vfs68_mem.c" "$vendor/file68/src/vfs68_null.c" "$vendor/file68/src/vfs68_z.c"
    "$vendor/file68/src/msg68.c" "$vendor/file68/src/option68.c" "$vendor/file68/src/registry68.c"
    "$vendor/file68/src/rsc68.c" "$vendor/file68/src/string68.c" "$vendor/file68/src/timedb68.c"
    "$vendor/file68/src/uri68.c"
)
compile_archive "$build/file68.a" "$build/file68" "-I$vendor/file68 -I$vendor/file68/sc68" "${file68_sources[@]}"

io68_sources=(io68.c mfp_io.c mfpemul.c mw_io.c mwemul.c paula_io.c paulaemul.c shifter_io.c ym_envel.c ym_blep.c ym_dump.c ym_io.c ym_puls.c ymemul.c)
io68_sources=("${io68_sources[@]/#/$vendor/libsc68/io68/}")
compile_archive "$build/io68.a" "$build/io68" "-I$vendor/libsc68 -I$vendor/file68" "${io68_sources[@]}"

emu68_sources=(emu68.c error68.c getea68.c inst68.c ioplug68.c mem68.c line0_68.c line1_68.c line2_68.c line3_68.c line4_68.c line5_68.c line6_68.c line7_68.c line8_68.c line9_68.c lineA_68.c lineB_68.c lineC_68.c lineD_68.c lineE_68.c lineF_68.c table68.c)
emu68_sources=("${emu68_sources[@]/#/$vendor/libsc68/emu68/}")
compile_archive "$build/emu68.a" "$build/emu68" "-I$vendor/libsc68 -I$vendor/libsc68/emu68 -I$vendor/file68" "${emu68_sources[@]}"

libsc68_sources=(
    "$vendor/libsc68/src/api68.c" "$vendor/libsc68/src/conf68.c" "$vendor/libsc68/src/libsc68.c" "$vendor/libsc68/src/mixer68.c"
    "$vendor/libsc68/dial68/dial68.c" "$vendor/libsc68/dial68/dial_conf.c" "$vendor/libsc68/dial68/dial_tsel.c" "$vendor/libsc68/dial68/dial_finf.c"
)
compile_archive "$build/libsc68.a" "$build/libsc68" "-I$vendor/libsc68/sc68 -I$vendor/libsc68 -I$vendor/file68 -I$vendor/file68/sc68 -I$vendor/sc68-libc" "${libsc68_sources[@]}"

g++ -std=c++17 -O2 -Wall -Wextra -Wpedantic -fPIC -shared sndh.cc \
    "$build/libsc68.a" "$build/io68.a" "$build/emu68.a" "$build/file68.a" \
    -o sndh.so -laudcore -laudtag -lz -lm
