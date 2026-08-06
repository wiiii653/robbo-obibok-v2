#include <cstdint>
#include <cstring>
#include <utility>
#include <vector>

#include <libaudcore/i18n.h>
#include <libaudcore/plugin.h>

#include "vendor/stsound/StSoundLibrary/StSoundLibrary.h"

class YmPlugin final : public InputPlugin
{
public:
    static const char * const exts[];
    static const char * const mimes[];
    static constexpr PluginInfo info = {N_("YM Player (ST-Sound)"), "ym", nullptr, nullptr, 0};
    constexpr YmPlugin() : InputPlugin(info, InputInfo().with_priority(5).with_exts(exts).with_mimes(mimes)) {}

    bool is_our_file(const char *, VFSFile & file) override {
        char header[16];
        int bytes = file.fread(header, 1, sizeof header);
        if (bytes < 4) return false;
        if (!std::memcmp(header, "YM5!", 4) || !std::memcmp(header, "YM6!", 4)) return true;
        // LHa stores its one-byte header size and checksum before "-lh5-".
        for (int i = 0; i + 5 <= bytes; i++)
            if (!std::memcmp(header + i, "-lh5-", 5)) return true;
        return false;
    }
    bool read_tag(const char *, VFSFile & file, Tuple & tuple, Index<char> *) override {
        Index<char> data = file.read_all(); YMMUSIC * music = load(data);
        if (!music) return false;
        ymMusicInfo_t info {}; ymMusicGetInfo(music, &info); set_tuple(tuple, info); ymMusicDestroy(music); return true;
    }
    bool play(const char *, VFSFile & file) override {
        Index<char> data = file.read_all(); YMMUSIC * music = load(data);
        if (!music) return false;
        ymMusicInfo_t info {}; ymMusicGetInfo(music, &info);
        Tuple tuple = get_playback_tuple(); set_tuple(tuple, info); set_playback_tuple(std::move(tuple));
        open_audio(FMT_S16_NE, sample_rate, 2);
        std::vector<ymsample> mono(buffer_frames); std::vector<int16_t> stereo(buffer_frames * 2);
        while (!check_stop()) {
            int seek = check_seek();
            if (seek >= 0 && ymMusicIsSeekable(music)) ymMusicSeek(music, static_cast<ymu32>(seek));
            if (!ymMusicCompute(music, mono.data(), buffer_frames)) break;
            for (int i = 0; i < buffer_frames; i++) stereo[2 * i] = stereo[2 * i + 1] = mono[i];
            write_audio(stereo.data(), static_cast<int>(stereo.size() * sizeof stereo[0]));
        }
        ymMusicDestroy(music); return true;
    }
private:
    static constexpr int sample_rate = 44100, buffer_frames = 1024;
    static YMMUSIC * load(Index<char> & data) {
        if (data.len() <= 0) return nullptr;
        YMMUSIC * music = ymMusicCreateWithRate(sample_rate);
        if (!music || !ymMusicLoadMemory(music, data.begin(), data.len())) { if (music) ymMusicDestroy(music); return nullptr; }
        ymMusicSetLoopMode(music, YMFALSE); return music;
    }
    static void set_tuple(Tuple & tuple, const ymMusicInfo_t & info) {
        if (info.pSongName && info.pSongName[0]) tuple.set_str(Tuple::Title, info.pSongName);
        if (info.pSongAuthor && info.pSongAuthor[0]) tuple.set_str(Tuple::Artist, info.pSongAuthor);
        if (info.pSongComment && info.pSongComment[0]) tuple.set_str(Tuple::Comment, info.pSongComment);
        if (info.pSongType && info.pSongType[0]) tuple.set_str(Tuple::Codec, info.pSongType);
        if (info.musicTimeInMs >= 0) tuple.set_int(Tuple::Length, info.musicTimeInMs);
    }
};
const char * const YmPlugin::exts[] = {"ym", nullptr};
const char * const YmPlugin::mimes[] = {"audio/x-ym", "audio/ym", nullptr};
__attribute__((visibility("default"))) YmPlugin aud_plugin_instance;
