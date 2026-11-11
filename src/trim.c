/*
 * Trim to Region on a Clip pad (blackbox#t-040, notes/re/x4-trim.md). DRAFT: built and run under Unicorn, test_trim.py owed.
 *
 * Stock offers the File menu's Trim only on a Sample pad (x4 §8), and FUN_080A0DD4 fills the save's loop and crop only
 * in Pad Mode 0 / 3 (x4 §3). The disk copy crops by the meta whatever the mode (x4 §7). Three hooks open it for a Clip
 * pad whose Region plays a loop (the bracket's rule, is_loop in clipwin_b2.c):
 *
 * - the menu, bl FUN_080BD566 @0x080B3620 (trim_thunk.S): Trim on as well for such a pad, own file, MultiSam 0;
 * - the write request, bl 0x0804CA88 @0x080A0FD0 in FUN_080A0DD4 (trim_thunk.S adds the cell and the trim flag): on a
 *   trim, stock's smpl loop {LS, LE, forward} and crop [LS - F, LE) into the meta, so the cut file is [LS - F, LE)
 *   with an smpl loop [F, end) (x4 §6); a Save (trim 0) is untouched;
 * - the reload, bl FUN_080A0AC8(app, path, cell, 0) @0x080A0FE0, on the trim path only: the region is read before it
 *   (the reload zeroes Loop Start), then the record's fresh byte is cleared and Loop Start := F, so the non-fresh 0x1B
 *   keeps the pad's rows and the 0xE that follows posts Loop Start with Loop End = the cut length (x4 §8, §9).
 *
 * No state between the hooks: the cave has no .bss, and each hook reads the pad's store itself, which nothing writes
 * between the request and the reload.
 *
 * F = Loop Fade's pre-roll, (int)((LE - LS) x row / 1000), at most Loop Start (clipwin_b2.c, x4 §6's clamp): the cut
 * keeps it so Loop Fade sounds the same and a second Trim cuts nothing more. Region, Slip, Loop Len, Fit and Loop Fade
 * are rows stock's reload does not write (x4 §4); they stay.
 *
 * Trim is refused while another pad of the preset names the same file: stock's trim reloads those too (plan rev 1,
 * Risks). Stock finds them in FUN_080A0DD4 @0x080A0F3A..0x080A0F92 - every cell, rows 0-3 x cols 0-4, but the trimmed
 * one, its path printed from the name its store holds at +0x18 (FUN_08098D0C, FUN_080460BA) and strncmp'd, 0xff, to the
 * trim's path. The format is the same for every cell, so the same name is the same path: trim_ok compares the names.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)

typedef int32_t (*setting_fn)(const void *store, unsigned id);
typedef void (*setting_set_fn)(void *store, unsigned id, int32_t value);
typedef void (*enable_fn)(void *menu, unsigned item, int on);
typedef void (*reload_fn)(uint8_t *app, const char *path, const void *cell, int z);
typedef void (*request_fn)(void *host, void *asset, void *meta, const char *path);
typedef void (*smpl_fn)(void *meta, unsigned index, const void *loop);
typedef void (*crop_fn)(void *meta, int32_t start, int32_t length);
typedef int (*strncmp_fn)(const char *a, const char *b, unsigned n);

#define fw_setting      ((setting_fn)FN(0x08093e9c))
#define fw_setting_set  ((setting_set_fn)FN(0x08093ecc))
#define fw_enable       ((enable_fn)FN(0x080bd566))
#define fw_reload       ((reload_fn)FN(0x080a0ac8))
#define fw_request      ((request_fn)FN(0x0804ca88))
#define fw_smpl         ((smpl_fn)FN(0x08077738))
#define fw_crop         ((crop_fn)FN(0x0807775c))
#define fw_strncmp      ((strncmp_fn)FN(0x080c8b48))

#define APP             0x24020088u
#define APP_PADS        (APP + 0x1840u)          /* the app's pad stores: + row * 0xf0 + col * 0x30 */
#define PAD_STORE(r, c) ((const uint8_t *)(APP_PADS + (r) * 0xf0u + (c) * 0x30u))   /* FUN_08098D0C, cols 0-4 */
#define PAD_NAME(r, c)  (*(const char *const *)(PAD_STORE(r, c) + 0x18))   /* FUN_080460BA: the file name, 0xff max */
#define APP_FRESH(r, c) (*(volatile uint8_t *)(APP + 0x8a96u + (r) * 0x78u + (c) * 0x18u))   /* x4 §4 */
#define P_PAD_MODE      0x8b
#define PAD_MODE_CLIP   1
#define P_LENGTH        0x90
#define P_LOOP_START    0x91
#define P_LOOP_END      0x92
#define P_LOOP_FADE     0xfa
#define LOOP_FADE_MAX   1000
#define P_REGION        0x150
#define REGION_FILE     1

int32_t clipwin_flen(unsigned q);   /* clipwin.c: the engine's length of pad q's file, 0 when it has none */

struct cell { uint32_t tag; uint16_t code, _r; };   /* a pad cell: code = row << 4 | col (x3 §1) */
struct cut { int32_t ls, le, f; unsigned row, col; };

/* Another cell of the preset names pad (row, col)'s file - or the pad names none: stock's own loop, by name. */
static int shared(unsigned row, unsigned col)
{
    const char *own = PAD_NAME(row, col);
    if (!own || !*own)
        return 1;
    for (unsigned r = 0; r < 4; r++)
        for (unsigned c = 0; c < 5; c++) {
            const char *name = PAD_NAME(r, c);
            if ((r != row || c != col) && name && !fw_strncmp(name, own, 0xff))
                return 1;
        }
    return 0;
}

/* The pad's region, when Trim may cut it: a Clip pad whose Region plays a loop (is_loop, clipwin_b2.c). */
static int trim_ok(const struct cell *cell, struct cut *t)
{
    unsigned code = cell->code, row = (code & 0xff) >> 4, col = code & 0xf;
    if ((code & 0x1f00) || row >= 4 || col >= 4)
        return 0;
    const void *st = (const void *)(APP_PADS + row * 0xf0u + col * 0x30u);
    if (fw_setting(st, P_PAD_MODE) != PAD_MODE_CLIP)
        return 0;
    int32_t ls = fw_setting(st, P_LOOP_START), le = fw_setting(st, P_LOOP_END), len = clipwin_flen(row * 4 + col);
    if (len <= 0)
        len = fw_setting(st, P_LENGTH);
    /* ls 0 refused too: the cut's loop would be its whole file, which the Clip Window plays as File (stock's pass,
     * a tail and a gap where a beat step overruns it) instead of as the region it was (#t-040 turn 8, Rig) */
    if (fw_setting(st, P_REGION) == REGION_FILE || ls <= 0 || ls >= le || le > len)
        return 0;
    if (shared(row, col))
        return 0;
    int32_t fade = fw_setting(st, P_LOOP_FADE);
    /* clipwin_b2.c's F, the same float maths, so the pre-roll kept is the one Loop Fade reads */
    int32_t f = fade > 0 && fade <= LOOP_FADE_MAX ? (int32_t)((float)(le - ls) * ((float)fade / 1000.0f)) : 0;
    t->ls = ls;
    t->le = le;
    /* at least one frame kept before Loop Start, so the cut's loop [F, end) is never the whole file (ls >= 1 here) */
    f = f < 1 ? 1 : f;
    t->f = f < ls ? f : ls;
    t->row = row;
    t->col = col;
    return 1;
}

/* trim_thunk.S, from bl FUN_080BD566(menu, 0x124, on) @0x080B3620 when the file is the pad's own and MultiSam is 0 */
void trim_menu(void *menu, unsigned item, int on, const struct cell *cell)
{
    struct cut t;
    if (!on && trim_ok(cell, &t))
        on = 1;
    fw_enable(menu, item, on);
}

/* trim_thunk.S, from bl 0x0804CA88(host, asset, meta, path) @0x080A0FD0: cell = r6, trim = FUN_080A0DD4's [sp, #0x10] */
void trim_write(void *host, void *asset, void *meta, const char *path, const struct cell *cell, int trim)
{
    struct cut t;
    if (trim && trim_ok(cell, &t)) {
        struct { uint32_t start, end; uint8_t type; } loop = {(uint32_t)t.ls, (uint32_t)t.le, 0};
        fw_smpl(meta, 0, &loop);
        fw_crop(meta, t.ls - t.f, t.le - t.ls + t.f);
    }
    fw_request(host, asset, meta, path);
}

/* Replaces bl FUN_080A0AC8(app, path, cell, 0) @0x080A0FE0, FUN_080A0DD4's reload on the trim path */
void trim_reload(uint8_t *app, const char *path, const struct cell *cell, int z)
{
    struct cut t;
    int clip = trim_ok(cell, &t);
    fw_reload(app, path, cell, z);
    if (clip) {
        APP_FRESH(t.row, t.col) = 0;
        fw_setting_set((void *)(APP_PADS + t.row * 0xf0u + t.col * 0x30u), P_LOOP_START, t.f);
    }
}
