#include <algorithm>
#include <cstdint>
#include <cstring>
#include <utility>
#include <vector>

#include <libaudcore/i18n.h>
#include <libaudcore/plugin.h>

extern "C" {
#include "vendor_sc68/libsc68/sc68/sc68.h"
}

class SndhPlugin final : public InputPlugin
{
public:
    static const char * const exts[];
    static const char * const mimes[];
    static constexpr PluginInfo info = {N_("Atari ST SNDH Player (sc68)"), "sndh", nullptr, nullptr, 0};

    constexpr SndhPlugin() : InputPlugin(info, InputInfo(InputPlugin::FlagSubtunes)
        .with_priority(5).with_exts(exts).with_mimes(mimes)) {}

    bool init() override {
        sc68_init_t init {};
        char program[] = "audacious";
        char * argv[] = {program};
        init.argc = 1;
        init.argv = argv;
        init.debug_clr_mask = -1;
        init.flags.no_load_config = 1;
        init.flags.no_save_config = 1;
        return sc68_init(&init) == 0;
    }

    void cleanup() override { sc68_shutdown(); }

    bool is_our_file(const char *, VFSFile & file) override {
        // Delegate detection to the file68 loader: it validates SNDH,
        // ICE!-compressed and LZH-compressed headers (like the reference
        // sc68-audacious plugin's plg_is_our()).
        Index<char> data = file.read_all();
        if (data.len() <= 0) return false;
        sc68_disk_t disk = sc68_disk_load_mem(data.begin(), data.len());
        if (!disk) return false;
        sc68_disk_free(disk);
        return true;
    }

    bool read_tag(const char *, VFSFile & file, Tuple & tuple, Index<char> *) override {
        Index<char> data = file.read_all();
        sc68_disk_t disk = load_disk(data);
        if (!disk) return false;
        sc68_music_info_t music {};
        bool ok = sc68_music_info(nullptr, &music, 1, disk) == 0;
        if (ok) set_tuple(tuple, music, 1);
        sc68_disk_free(disk);
        return ok;
    }

    bool play(const char *, VFSFile & file) override {
        Index<char> data = file.read_all();
        sc68_t * player = create_player(data);
        if (!player) return false;

        int track = selected_track();
        sc68_music_info_t music {};
        if (sc68_music_info(player, &music, 1, nullptr) != 0) {
            sc68_destroy(player);
            return false;
        }
        track = std::clamp(track, 1, music.tracks);
        if (sc68_play(player, track, 0) < 0) {
            sc68_destroy(player);
            return false;
        }

        Tuple tuple = get_playback_tuple();
        if (sc68_music_info(player, &music, track, nullptr) == 0)
            set_tuple(tuple, music, track);
        set_playback_tuple(std::move(tuple));
        open_audio(FMT_S16_NE, sample_rate, 2);

        std::vector<int16_t> buffer(buffer_frames * 2);
        while (!check_stop()) {
            int seek = check_seek();
            if (seek >= 0 && !seek_to(player, track, seek, buffer)) break;
            int frames = buffer_frames;
            int status = sc68_process(player, buffer.data(), &frames);
            // Only SC68_END ends the track (SC68_ERROR sets all bits).
            // SC68_IDLE/SC68_CHANGE on the first call are normal init.
            if (status & SC68_END) break;
            if (frames > 0)
                write_audio(buffer.data(), frames * 2 * static_cast<int>(sizeof(int16_t)));
        }
        sc68_stop(player);
        sc68_destroy(player);
        return true;
    }

private:
    static constexpr int sample_rate = 44100, buffer_frames = 1024;

    static sc68_disk_t load_disk(const Index<char> & data) {
        return data.len() > 0 ? sc68_disk_load_mem(data.begin(), data.len()) : nullptr;
    }

    static sc68_t * create_player(const Index<char> & data) {
        if (data.len() <= 0) return nullptr;
        sc68_create_t create {};
        create.sampling_rate = sample_rate;
        sc68_t * player = sc68_create(&create);
        if (!player || sc68_load_mem(player, data.begin(), data.len()) != 0) {
            sc68_destroy(player);
            return nullptr;
        }
        return player;
    }

    static int selected_track() {
        int track = get_playback_tuple().get_int(Tuple::Subtune);
        return track > 0 ? track : 1;
    }

    static bool seek_to(sc68_t * player, int track, int milliseconds,
                        std::vector<int16_t> & buffer) {
        if (sc68_play(player, track, 0) < 0) return false;
        int remaining = std::max(0, milliseconds);
        while (remaining > 0 && !check_stop()) {
            int frames = std::min(buffer_frames, (remaining * sample_rate + 999) / 1000);
            int status = sc68_process(player, buffer.data(), &frames);
            if (status & SC68_END)
                return false;
            if (frames > 0)
                remaining -= std::max(1, frames * 1000 / sample_rate);
        }
        return true;
    }

    static void set_tuple(Tuple & tuple, const sc68_music_info_t & music, int track) {
        if (music.title && music.title[0]) tuple.set_str(Tuple::Title, music.title);
        if (music.artist && music.artist[0]) tuple.set_str(Tuple::Artist, music.artist);
        if (music.album && music.album[0] && (!music.title || std::strcmp(music.album, music.title)))
            tuple.set_str(Tuple::Album, music.album);
        if (music.genre && music.genre[0]) tuple.set_str(Tuple::Genre, music.genre);
        if (music.trk.time_ms) tuple.set_int(Tuple::Length, music.trk.time_ms);
        tuple.set_int(Tuple::Track, track);
        tuple.set_int(Tuple::Subtune, track);
        std::vector<short> subtunes;
        subtunes.reserve(music.tracks);
        for (int i = 1; i <= music.tracks; ++i) subtunes.push_back(static_cast<short>(i));
        tuple.set_subtunes(static_cast<short>(subtunes.size()), subtunes.data());
        tuple.set_format("SNDH (sc68)", 2, sample_rate, 0);
    }
};

const char * const SndhPlugin::exts[] = {"sndh", "snd", nullptr};
const char * const SndhPlugin::mimes[] = {"audio/x-sndh", "audio/sndh", nullptr};
__attribute__((visibility("default"))) SndhPlugin aud_plugin_instance;
