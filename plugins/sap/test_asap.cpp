#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>

extern "C" {
#include "vendor/asap-8.0.0/asap.h"
}

static void put16(std::ofstream & out, uint16_t value) { out.write(reinterpret_cast<const char *>(&value), 2); }
static void put32(std::ofstream & out, uint32_t value) { out.write(reinterpret_cast<const char *>(&value), 4); }

int main(int argc, char ** argv) {
    if (argc != 3) { std::fprintf(stderr, "Usage: %s INPUT.sap OUTPUT.wav\n", argv[0]); return 2; }
    std::ifstream input(argv[1], std::ios::binary);
    std::vector<uint8_t> data((std::istreambuf_iterator<char>(input)), {});
    ASAP * as = ASAP_New();
    if (data.empty() || !as || !ASAP_Load(as, argv[1], data.data(), static_cast<int>(data.size()))) {
        std::fprintf(stderr, "ASAP_Load failed: %s\n", argv[1]); if (as) ASAP_Delete(as); return 1;
    }
    ASAP_SetSampleRate(as, 44100);
    const ASAPInfo * info = ASAP_GetInfo(as);
    int type = ASAPInfo_GetTypeLetter(info), songs = ASAPInfo_GetSongs(info), channels = ASAPInfo_GetChannels(info);
    std::printf("file=%s\ntype=%c songs=%d channels=%d title=%s\nauthor=%s date=%s\ndurations_ms=", argv[1], type ? type : '?', songs, channels, ASAPInfo_GetTitle(info), ASAPInfo_GetAuthor(info), ASAPInfo_GetDate(info));
    for (int i = 0; i < songs; ++i) std::printf("%s%d%s", i ? "," : "", ASAPInfo_GetDuration(info, i), ASAPInfo_GetLoop(info, i) ? " LOOP" : "");
    std::printf("\n");
    constexpr int rate = 44100, frames_wanted = rate * 30, block = 1024;
    if (!ASAP_PlaySong(as, 0, 30000)) { ASAP_Delete(as); return 1; }
    std::vector<uint8_t> generated(block * channels * sizeof(int16_t));
    std::vector<int16_t> pcm; pcm.reserve(frames_wanted * 2);
    double sum = 0; size_t frames = 0;
    while (frames < frames_wanted) {
        int bytes = ASAP_Generate(as, generated.data(), static_cast<int>(generated.size()), ASAPSampleFormat_S16_L_E);
        if (bytes <= 0) break;
        const auto * samples = reinterpret_cast<const int16_t *>(generated.data());
        int blocks = bytes / (channels * static_cast<int>(sizeof(int16_t)));
        for (int i = 0; i < blocks; ++i) {
            int16_t left = samples[i * channels], right = channels == 2 ? samples[i * 2 + 1] : left;
            pcm.push_back(left); pcm.push_back(right); double value = left / 32768.0; sum += value * value; ++frames;
        }
    }
    ASAP_Delete(as);
    double rms = frames ? std::sqrt(sum / frames) : 0;
    std::printf("rendered_frames=%zu rms=%.8f\n", frames, rms);
    if (frames == 0 || rms <= .001) { std::fprintf(stderr, "PCM is silent or absent\n"); return 1; }
    std::ofstream out(argv[2], std::ios::binary); uint32_t bytes = static_cast<uint32_t>(pcm.size() * sizeof(int16_t));
    out.write("RIFF", 4); put32(out, 36 + bytes); out.write("WAVEfmt ", 8); put32(out, 16); put16(out, 1); put16(out, 2); put32(out, rate); put32(out, rate * 4); put16(out, 4); put16(out, 16); out.write("data", 4); put32(out, bytes); out.write(reinterpret_cast<const char *>(pcm.data()), bytes);
    return out ? 0 : 1;
}
