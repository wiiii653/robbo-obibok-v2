#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>
#include "vendor/stsound/StSoundLibrary/StSoundLibrary.h"
static void u16(std::ofstream &o,uint16_t v){o.write(reinterpret_cast<const char*>(&v),2);} static void u32(std::ofstream&o,uint32_t v){o.write(reinterpret_cast<const char*>(&v),4);}
int main(int argc,char **argv) {
    if(argc!=3){std::fprintf(stderr,"Usage: %s INPUT.ym OUTPUT.wav\n",argv[0]);return 2;}
    std::ifstream in(argv[1],std::ios::binary); std::vector<char> input((std::istreambuf_iterator<char>(in)),{});
    if(input.empty()){std::fprintf(stderr,"Cannot read input: %s\n",argv[1]);return 2;}
    YMMUSIC *m=ymMusicCreateWithRate(44100);
    if(!m||!ymMusicLoadMemory(m,input.data(),input.size())){std::fprintf(stderr,"Load failed: %s\n",m?ymMusicGetLastError(m):"allocation failure");if(m)ymMusicDestroy(m);return 1;}
    ymMusicSetLoopMode(m,YMFALSE); ymMusicInfo_t info{};ymMusicGetInfo(m,&info);std::printf("duration_ms=%d title=%s\n",info.musicTimeInMs,info.pSongName?info.pSongName:"");
    constexpr int rate=44100,seconds=30,block=1024;std::vector<ymsample> mono(block);std::vector<int16_t> pcm;pcm.reserve(rate*seconds*2);double sum=0;size_t frames=0;
    for(int done=0;done<rate*seconds;done+=block){int want=std::min(block,rate*seconds-done);if(!ymMusicCompute(m,mono.data(),want))break;for(int i=0;i<want;i++){pcm.push_back(mono[i]);pcm.push_back(mono[i]);double v=mono[i]/32768.0;sum+=v*v;frames++;}}
    ymMusicDestroy(m);double rms=frames?std::sqrt(sum/frames):0;std::printf("rendered_frames=%zu rms=%.8f\n",frames,rms);if(!frames||rms<=.001){std::fprintf(stderr,"PCM is silent or absent\n");return 1;}
    std::ofstream out(argv[2],std::ios::binary);uint32_t bytes=pcm.size()*sizeof(int16_t);out.write("RIFF",4);u32(out,36+bytes);out.write("WAVEfmt ",8);u32(out,16);u16(out,1);u16(out,2);u32(out,rate);u32(out,rate*4);u16(out,4);u16(out,16);out.write("data",4);u32(out,bytes);out.write(reinterpret_cast<const char*>(pcm.data()),bytes);return out?0:1;
}
