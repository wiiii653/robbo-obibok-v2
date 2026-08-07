/* Test sc68 API on a real file: disk load vs player load vs process. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "vendor_sc68/libsc68/sc68/sc68.h"

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s <file>\n", argv[0]); return 1; }
    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror("fopen"); return 1; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    char *buf = malloc(sz); if (!buf) return 1;
    fread(buf, 1, sz, f); fclose(f);

    sc68_init_t init; memset(&init, 0, sizeof init);
    init.argc = 1;
    char *argv0[] = {"test"};
    init.argv = argv0;
    int ri = sc68_init(&init);
    printf("sc68_init: %d\n", ri);

    sc68_disk_t disk = sc68_disk_load_mem(buf, (unsigned)sz);
    printf("sc68_disk_load_mem: %s\n", disk ? "OK" : "FAIL");
    if (disk) {
        sc68_music_info_t mi; memset(&mi, 0, sizeof mi);
        if (sc68_music_info(NULL, &mi, 1, disk) == 0)
            printf("  tracks: %d | '%s' by '%s' time_ms=%d\n",
                   mi.tracks, mi.title ? mi.title : "", mi.artist ? mi.artist : "", mi.trk.time_ms);
        sc68_disk_free(disk);
    }

    sc68_create_t cr; memset(&cr, 0, sizeof cr);
    cr.sampling_rate = 44100;
    sc68_t *pl = sc68_create(&cr);
    printf("sc68_create: %s\n", pl ? "OK" : "FAIL");
    if (pl) {
        int rl = sc68_load_mem(pl, buf, (unsigned)sz);
        printf("sc68_load_mem: %d\n", rl);
        if (rl == 0) {
            sc68_music_info_t mi; memset(&mi, 0, sizeof mi);
            int rc = sc68_music_info(pl, &mi, 1, NULL);
            printf("music_info: %d time_ms=%d title='%s' artist='%s'\n", rc,
                   mi.trk.time_ms, mi.title ? mi.title : "", mi.artist ? mi.artist : "");
            int rp = sc68_play(pl, 1, 0);
            printf("sc68_play: %d\n", rp);
            short out[4096];
            int frames = 2048;
            int rs = sc68_process(pl, out, &frames);
            printf("sc68_process: %d frames=%d samples[0..3]=%d,%d,%d,%d\n",
                   rs, frames, out[0], out[1], out[2], out[3]);
            sc68_stop(pl);
        }
        sc68_destroy(pl);
    }
    sc68_shutdown();
    free(buf);
    return 0;
}
