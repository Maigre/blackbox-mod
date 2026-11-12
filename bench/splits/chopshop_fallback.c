/*
 * ChopShop without bank 2 (bench/splits/chopshop_hand.py, for bench/b2split.py): the one fallback a hand has to write.
 * The Mode list keeps its 7 entries whatever bank 2 does (a data patch, patches/slice.py), so stock's set handler must
 * still get the stored mode, not the list position: ChopShop -> Slicer (with the flag, so a pad picked here is
 * ChopShop again once bank 2 is back), Granular.. -> one down; entering or leaving ChopShop clears the Tempo code, which
 * a Clip pad would read as its selection's Beats. The Chop / Roll / Tempo rows never show without bank 2
 * (chop_pages falls back to stock's pages), so their ids pass through as stock would see them.
 */
#include <stdint.h>

#define FN(addr) ((addr) | 1u)
#define fw_setting   ((int (*)(const void *, int))FN(0x08093e9c))
#define fw_set       ((void (*)(void *, int, int))FN(0x08093ecc))
#define fw_cell      ((uint8_t *(*)(uint8_t *, void *))FN(0x08098d0c))
#define fw_set_param ((int (*)(uint8_t *, void *, int, int, int))FN(0x0809fa50))
#define P_MODE       0x8b
#define P_CHOP       0x14d
#define P_SEL_BEATS  0x15e      /* ChopShop's Tempo code / the Clip selection's Beats: cleared when ChopShop is entered or left */
#define POS_CHOP     3
#define MODE_SLICER  2

int chop_set_off(uint8_t *app, void *ref, int id, int value, int extra)
{
    if (id == P_MODE) {
        uint8_t *cell = fw_cell(app, ref);
        int want = value == POS_CHOP;
        if (cell) {
            int was = fw_setting(cell, P_MODE) == MODE_SLICER && fw_setting(cell, P_CHOP);
            fw_set(cell, P_CHOP, want);
            if (want != was)
                fw_set(cell, P_SEL_BEATS, 0);
        }
        value = value == POS_CHOP ? MODE_SLICER : value > POS_CHOP ? value - 1 : value;
    }
    return fw_set_param(app, ref, id, value, extra);
}
