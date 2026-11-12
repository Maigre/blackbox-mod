/*
 * ChopShop: a fifth pad mode in the Mode list that is a Slicer underneath (0x8b = 2) plus the flag P_CHOP, so a project
 * stays a plain Slicer on stock firmware. Original 1010music Blackbox, firmware 3.1.9. research/slicer/MODE_LIST_RE.md.
 *
 * The list (data patch): Sample, Clip, Slicer, ChopShop, Granular, New Rec, New Multi (7 entries; stock has 6). The
 * popups give a POSITION; chop_set maps it to the stored value before stock's set handler sees it (stock sends the raw
 * value to the engine first): 3 -> Slicer + flag, 4.. -> 3.. The two popup highlights map back.
 * Entering ChopShop: Launch Mode Gate (a chop plays while the pad is held), Sync on and Stretch Cyclic (Stock does
 * not stretch a chop at all; Cyclic is the lightest model). Its POS page gets three rows of ours, at the top of the page: Chop (Off, 1/4, 1/2, Beat, 2 Beats, Bar, Find, Random: picking one runs it, chop.c; the same setting is
 * the ChopShop flag), Roll (any turn rolls new Find / Random chops; not stored) and Tempo (1/2, x1, x2 on the
 * detected tempo: kept in P_SEL_BEATS, unused on Slicer pads; a new sample or a mode change resets it). A new sample on a ChopShop pad keeps it ChopShop and chops it again.
 * CPU: none per audio block; UI events only.
 */
#include <stdint.h>
#include "chop.h"

#define FN(addr) ((addr) | 1u)
typedef int (*setting_fn)(const void *store, int param);
typedef void (*set_fn)(void *store, int param, int value);
typedef uint8_t *(*cell_fn)(uint8_t *app, void *ref);
typedef int (*set_param_fn)(uint8_t *app, void *ref, int id, int value, int extra);
typedef int (*popup_fn)(uint8_t *popup, int pos, int a, int b);
typedef int (*pages_fn)(uint8_t *app, void *ref, void *list, int page);
typedef void (*row_add_fn)(void *list, int id, int value);
typedef void (*register_list_fn)(void *table, int param, const char *label, const char *const *names, int count,
                                 const char *xml);
typedef void (*register_num_fn)(void *table, int param, int type, const char *label, int min, int max, const char *xml);
typedef void (*store_add_fn)(void *store, int param, int value);
typedef void (*app_post_fn)(uint8_t *queue, void *msg);
#define fw_setting       ((setting_fn)FN(0x08093e9c))
#define fw_set           ((set_fn)FN(0x08093ecc))
#define fw_cell          ((cell_fn)FN(0x08098d0c))
#define fw_set_param     ((set_param_fn)FN(0x0809fa50))
#define fw_popup_value   ((popup_fn)FN(0x080bd74e))
#define fw_pages         ((pages_fn)FN(0x08098d40))
#define fw_row_add       ((row_add_fn)FN(0x080a5038))
#define fw_register_list ((register_list_fn)FN(0x0808c0d8))
#define fw_register_num  ((register_num_fn)FN(0x0808c12c))
#define fw_store_add     ((store_add_fn)FN(0x08093ef6))
#define fw_app_post      ((app_post_fn)FN(0x080b5758))

#define P_MODE       0x8b
#define P_LAUNCH     0x93       /* Trigger, Gate, Toggle */
#define P_SLICESYNC  0xf4
#define P_STRETCH    0x14c      /* stretch.c: Stock, Smooth, Keyframe, Cyclic */
#define STRETCH_CYCLIC 3
#define P_CHOP       0x14d      /* 0 = not ChopShop, 1 = ChopShop with Chop Off, 2.. = the chop type (one store entry: a pad
                                   store holds 96 and a Sample pad is at 95 with it; test_savexml checks the cap) */
#define P_CHOP_ROLL  0x161      /* Roll: a row with no store entry (any turn re-rolls; nothing to save) */
#define P_CHOP_TEMPO 0x162      /* Tempo: 1/2, x1, x2 on the detected tempo (10-27: the detector can read a song at half time).
                                   No store entry of its own: kept in P_SEL_BEATS (chop.c), which Slicer pads never read */
#define P_SEL_BEATS  0x15e
#define MODE_SLICER  2
#define POS_CHOP     3          /* the list position of ChopShop */


struct str_bank *stretch_bank(void);                 /* clipsel.c */
void sel_ask_pad(int q);
int sel_take_pad(int q, float *bpm, float *phase, unsigned *frate);
int b2_live(void);                                    /* cpu.c */
int chopb_set(const struct chop_cave *cv, uint8_t *app, void *ref, int id, int value, int extra);   /* chopmode_b2.c */
int chopb_pages(uint8_t *app, void *ref, void *list, int page);
void chopb_view_tick(const struct chop_cave *cv, uint8_t *view, void *flags);
void chopb_header_post(const struct chop_cave *cv, uint8_t *queue, void *msg);

/* the stock names (pointers read from the table at 0x080ec87c), ChopShop after Slicer */
const char *const chop_mode_names[7] = {
    (const char *)0x080ce7ac, (const char *)0x080ce7b4, (const char *)0x080ce7bc, "ChopShop",
    (const char *)0x080ce7c4, (const char *)0x080ce7d0, (const char *)0x080ce7d8,
};
static const char *const type_names[9] = { "--", "Off", "1/4", "1/2", "Beat", "2 Beats", "Bar", "Find", "Random" };
static const char *const tempo_names[3] = { "1/2", "x1", "x2" };

static int is_chop(const void *store)
{
    return store && fw_setting(store, P_MODE) == MODE_SLICER && fw_setting(store, P_CHOP);
}

static int pos_of(const void *store, int mode)       /* stored mode -> list position */
{
    if (mode == MODE_SLICER && is_chop(store))
        return POS_CHOP;
    return mode >= 3 ? mode + 1 : mode;
}

/* the Mode popups' highlight: Waveform screen (BL @0x080a5a5a) and the pad view (BL @0x080b8aa2) */
int chop_show_wave(uint8_t *popup, int mode, int a, int b)
{
    return fw_popup_value(popup, pos_of(popup - 0x23fc + 0x2370, mode), a, b);
}

int chop_show_pad(uint8_t *popup, int mode, int a, int b)
{
    return fw_popup_value(popup, pos_of(popup - 0xe3bc + 0x7d8, mode), a, b);
}

/* The hooks (patches/slice.py) land here, in bank 1: bank 2's bodies (chopmode_b2.c) when it is live, else stock. The
   Mode list keeps its 7 entries either way (a data patch), so the set handler's fallback still maps the positions. */
const struct chop_cave chop_cave = { stretch_bank, sel_ask_pad, sel_take_pad };

int chop_set(uint8_t *app, void *ref, int id, int value, int extra)
{
    if (b2_live())
        return chopb_set(&chop_cave, app, ref, id, value, extra);
    if (id == P_MODE)
        value = value == POS_CHOP ? MODE_SLICER : value > POS_CHOP ? value - 1 : value;
    return fw_set_param(app, ref, id, value, extra);
}

int chop_pages(uint8_t *app, void *ref, void *list, int page)
{
    return b2_live() ? chopb_pages(app, ref, list, page) : fw_pages(app, ref, list, page);
}

#define fw_view_tick ((void (*)(uint8_t *, void *))FN(0x080b9590))
void chop_view_tick(uint8_t *view, void *flags)
{
    if (b2_live())
        chopb_view_tick(&chop_cave, view, flags);
    else
        fw_view_tick(view, flags);
}

void chop_header_post(uint8_t *queue, void *msg)
{
    if (b2_live())
        chopb_header_post(&chop_cave, queue, msg);
    else
        fw_app_post(queue, msg);
}

/* a fresh WAV header sets the pad's mode from the file (BL @0x0809dd28): a ChopShop pad stays ChopShop */
void chop_header_mode(void *cell, int id, int mode)
{
    if (fw_setting(cell, P_CHOP)) {
        if (fw_setting(cell, P_MODE) == MODE_SLICER)
            mode = MODE_SLICER;
        else
            fw_set(cell, P_CHOP, 0);                 /* a stale flag (the pad was changed without the reset): drop it */
    }
    fw_set(cell, id, mode);
}

/* clipsel.c sel_reset_cell, after every stock mode reset: the flag only lives on a Slicer */
void chop_invariant(void *store)
{
    if (store && fw_setting(store, P_MODE) != MODE_SLICER)
        fw_set(store, P_CHOP, 0);
}

void chop_register(void *table)
{
    fw_register_list(table, P_CHOP, "Chop:", type_names, 9, "chopshop");
    fw_register_num(table, P_CHOP_ROLL, 1, "Roll:", 0, 99, "choproll");
    fw_register_list(table, P_CHOP_TEMPO, "Tempo:", tempo_names, 3, "choptempo");
}

void chop_defaults(void *store)
{
    fw_store_add(store, P_CHOP, 0);
}
