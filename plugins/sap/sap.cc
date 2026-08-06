#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

#include <libaudcore/i18n.h>
#include <libaudcore/plugin.h>

extern "C" {
#include "vendor/asap-8.0.0/asap.h"
}

class SapPlugin final : public InputPlugin {
public:
    static const char * const exts[];
    static const char * const mimes[];
    static constexpr PluginInfo info = {N_("Atari SAP Player (ASAP)"), "sap", nullptr, nullptr, 0};
    constexpr SapPlugin() : InputPlugin(info, InputInfo().with_priority(4).with_exts(exts).with_mimes(mimes)) {}

    bool is_our_file(const char *, VFSFile & file) override {
        char header[3];
        return file.fread(header, 1, sizeof header) == sizeof header && !std::memcmp(header, "SAP", sizeof header);
    }

    bool read_tag(const char * filename, VFSFile & file, Tuple & tuple, Index<char> *) override {
        Index<char> data = file.read_all();
        ASAP * as = load(filename, data);
        if (!as) return false;
        set_tuple(tuple, ASAP_GetInfo(as));
        ASAP_Delete(as);
        return true;
    }

    bool play(const char * filename, VFSFile & file) override {
        Index<char> data = file.read_all();
        ASAP * as = load(filename, data);
        if (!as) return false;

        const ASAPInfo * module = ASAP_GetInfo(as);
        Tuple tuple = get_playback_tuple();
        set_tuple(tuple, module);
        set_playback_tuple(std::move(tuple));
        open_audio(FMT_S16_NE, sample_rate, 2);

        const int songs = ASAPInfo_GetSongs(module);
        std::vector<int> durations = song_durations(module);
        int song = 0;
        int initial_seek = check_seek();
        if (initial_seek >= 0 && !select_position(as, durations, initial_seek, song)) {
            ASAP_Delete(as);
            return false;
        }
        if (initial_seek < 0 && !ASAP_PlaySong(as, song, durations[song])) {
            ASAP_Delete(as);
            return false;
        }

        const bool source_stereo = ASAPInfo_GetChannels(module) == 2;
        std::vector<uint8_t> source(buffer_frames * (source_stereo ? 2 : 1) * sizeof(int16_t));
        std::vector<int16_t> stereo(buffer_frames * 2);
        while (!check_stop() && song < songs) {
            int seek = check_seek();
            if (seek >= 0 && !select_position(as, durations, seek, song)) break;
            int bytes = ASAP_Generate(as, source.data(), static_cast<int>(source.size()), ASAPSampleFormat_S16_L_E);
            if (bytes <= 0) {
                if (++song >= songs) break;
                if (!ASAP_PlaySong(as, song, durations[song])) break;
                continue;
            }
            if (source_stereo) {
                write_audio(source.data(), bytes);
            } else {
                const auto * mono = reinterpret_cast<const int16_t *>(source.data());
                int frames = bytes / static_cast<int>(sizeof(int16_t));
                for (int i = 0; i < frames; ++i) stereo[2 * i] = stereo[2 * i + 1] = mono[i];
                write_audio(stereo.data(), frames * 2 * static_cast<int>(sizeof(int16_t)));
            }
        }
        ASAP_Delete(as);
        return true;
    }

private:
    static constexpr int sample_rate = 44100;
    static constexpr int buffer_frames = 1024;
    static constexpr int fallback_duration_ms = 180000;

    static ASAP * load(const char * filename, const Index<char> & data) {
        if (data.len() <= 0 || data.len() > ASAPInfo_MAX_MODULE_LENGTH) return nullptr;
        ASAP * as = ASAP_New();
        if (!as || !ASAP_Load(as, filename, reinterpret_cast<const uint8_t *>(data.begin()), data.len())) {
            if (as) ASAP_Delete(as);
            return nullptr;
        }
        ASAP_SetSampleRate(as, sample_rate);
        return as;
    }

    static std::vector<int> song_durations(const ASAPInfo * info) {
        std::vector<int> result;
        for (int song = 0; song < ASAPInfo_GetSongs(info); ++song) {
            int duration = ASAPInfo_GetDuration(info, song);
            result.push_back(duration > 0 ? duration : fallback_duration_ms);
        }
        return result;
    }

    static bool select_position(ASAP * as, const std::vector<int> & durations, int absolute_ms, int & song) {
        absolute_ms = std::max(0, absolute_ms);
        song = 0;
        while (song + 1 < static_cast<int>(durations.size()) && absolute_ms >= durations[song]) {
            absolute_ms -= durations[song++];
        }
        return ASAP_PlaySong(as, song, durations[song]) && ASAP_Seek(as, absolute_ms);
    }

    static void set_tuple(Tuple & tuple, const ASAPInfo * info) {
        const char * title = ASAPInfo_GetTitle(info);
        const char * author = ASAPInfo_GetAuthor(info);
        const char * date = ASAPInfo_GetDate(info);
        if (title[0]) tuple.set_str(Tuple::Title, title);
        if (author[0]) tuple.set_str(Tuple::Artist, author);
        if (date[0]) tuple.set_str(Tuple::Date, date);
        char comment[64];
        int type = ASAPInfo_GetTypeLetter(info);
        std::snprintf(comment, sizeof comment, "Atari SAP%s%c", type ? " TYPE " : "", type ? type : ' ');
        tuple.set_str(Tuple::Comment, comment);
        int64_t total = 0;
        for (int duration : song_durations(info)) total += duration;
        tuple.set_int(Tuple::Length, static_cast<int>(std::min<int64_t>(total, INT32_MAX)));
    }
};

const char * const SapPlugin::exts[] = {"sap", nullptr};
const char * const SapPlugin::mimes[] = {"audio/x-sap", "audio/sap", nullptr};
__attribute__((visibility("default"))) SapPlugin aud_plugin_instance;
