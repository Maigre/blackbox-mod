/*
 * Munchi Delay's engine, in flash bank 2. Original 1010music Blackbox, firmware 3.1.9.
 *
 * Everything of Munchi that is DSP on its own state: TEMPO's granular delay, the reverb and the ducker (src/munchi,
 * MIT, see munchi.cpp's header for whose), started on the stock delay's lines and run one block at a time. The delay
 * slot's glue - the Type list, the knob page, the process hook, the send gate, the settings, the bus write - stays in
 * the cave (munchi.cpp) and calls the two entry points below, and only while bank 2 is live.
 *
 * Moved up from munchi.cpp as it was, code and memory layout unchanged: the same output, sample for sample, from the
 * same settings (test_munchi.py holds it to the bytes). What changed is where it runs, and that the settings arrive
 * as numbers (struct munchi_params) instead of being read from the store here: the store lookup is stock's code.
 *
 * LEAF CODE ONLY, like everything up here (test_bank2.py): nothing in this file may call outside bank 2. TEMPO's
 * classes are header-only and get compiled in here, and nothing else includes them, so none of their code can end
 * up in the cave. The one call the compiler would make on its own is memset, for value-initialising Munchi - and the
 * only memset is the cave's (munchi.cpp) - so the state is zeroed by hand and constructed without it.
 */
#include <stddef.h>
#include <stdint.h>
#include <new>
#include "munchi_dsp.h"

#pragma GCC optimize("Os", "no-tree-loop-distribute-patterns")

#include "munchi/tempo/granularDelay.h"
#include "munchi/tempo/reverb.h"
#include "munchi/tempo/SimpleCompressor.h"

#define MAGIC 0x4d554e31u                                 /* "MUN1" */
#define MAXN MUNCHI_MAXN

static const float clock_mul[3] = {1.f, .5f, 2.f};
static const float width_mul[4] = {1.f, 0.f, 2.5f, 5.f};

struct Munchi {
    uint32_t magic;
    mbuf_t *live, *frozen;
    granularDelay delay;
    daisysp::Reverb reverb;
    SimpleCompressor comp;
    clockManager clock;
    float wet_amt, reverb_amt, reverb_amt_target, reverb_boost, reverb_boost_target;
    float pulse_phase;
    long pulses;
    int last_wand, last_random, last_feedback, last_freeze, last_duck;
    float clock_mul;
    float wl[MAXN], wr[MAXN];
};

static_assert(sizeof(Munchi) <= 96000 * 4, "Munchi's state must fit the stock delay's 2 s line");

static void zero(void *p, uint32_t bytes)
{
    uint32_t *w = (uint32_t *)p;
    for (uint32_t i = 0; i < bytes / 4; i++)
        w[i] = 0;
}

static Munchi *start(void *st, uint32_t st_floats, mbuf_t *live, uint32_t live_floats, mbuf_t *frozen, uint32_t frozen_floats)
{
    if (!live || !frozen || !st || st_floats * 4 < sizeof(Munchi))
        return nullptr;
    uint32_t frames = live_floats;                              /* floats -> 16-bit stereo frames: same count */
    if (frozen_floats < frames)
        frames = frozen_floats;
    zero(live, frames * 4);
    zero(frozen, frames * 4);
    zero(st, sizeof(Munchi));
    Munchi *m = new (st) Munchi;                    /* TEMPO's classes expect zeroed memory: zero() has just done it */
    m->live = live;
    m->frozen = frozen;
    m->reverb.Init(48000.f);
    m->reverb.SetAmount(0.f);
    m->reverb.SetInputGain(.3f);
    m->reverb.SetLowpass(1.f);
    m->comp.Init();
    m->delay.Init(m->live, m->frozen, frames, &m->clock, false);
    m->wet_amt = 1.f;
    m->last_wand = m->last_random = m->last_feedback = m->last_freeze = m->last_duck = -1;
    m->clock_mul = 1.f;
    if (!MUNCHI_RNG)
        MUNCHI_RNG = 0x2545f491u;
    m->magic = MAGIC;
    return m;
}

/* FxEngine::setGranularMain / setGranularFeedback, as Munchi's wrapper has them */
static void set_main(Munchi *m, float val)
{
    m->delay.setMainControl(val);
    if (val > .55f) {
        float norm = (val - .55f) / (1.f - .55f);
        float r = chompi::fast_sqrt(norm);                     /* powf(norm, .5f) */
        m->reverb_amt_target = .25f + .65f * r;
        m->reverb_boost_target = val > .6f ? .3f : 0.f;
    } else {
        m->reverb_amt_target = 0.f;
        m->reverb_boost_target = 0.f;
    }
}

static void controls(Munchi *m, const munchi_params *p)
{
    int wand = p->wand, random = p->random;
    int feedback = p->feedback, freeze = p->freeze != 0;
    unsigned clock = (unsigned)p->clock, width = (unsigned)p->width;
    int duck = p->duck;
    m->clock_mul = clock_mul[clock < 3 ? clock : 0];
    MUNCHI_SPREAD = width_mul[width < 4 ? width : 0];
    if (wand != m->last_wand)
        set_main(m, daisysp::fclamp(wand * .001f, 0.f, 1.f));
    if (random != m->last_random)
        m->delay.setAltControl(daisysp::fclamp(random * .001f, 0.f, 1.f));
    if (feedback != m->last_feedback || duck != m->last_duck) {
        float v = daisysp::fclamp(feedback * .001f, 0.f, 1.f);
        m->delay.setFeedback(v);
        float amount = duck == 1 ? 0.f : duck == 2 ? .5f : duck == 3 ? 1.f : (v > .6f ? (v - .6f) / (1.f - .6f) : 0.f);
        m->comp.setAmount(amount);
    }
    if (m->last_freeze >= 0 && freeze != m->last_freeze && freeze != m->delay.getBufferLock())
        m->delay.toggleBufferLock();
    m->last_wand = wand;
    m->last_random = random;
    m->last_feedback = feedback;
    m->last_freeze = freeze;
    m->last_duck = duck;
}

static void run_clock(Munchi *m, float bpm, int frames)
{
    if (!(bpm > 0.f))
        bpm = 120.f;
    bpm *= m->clock_mul;            /* note lengths that would not fit the 4 s buffer are clamped in granularDelay.h */
    m->clock.setBpm(bpm);
    m->pulse_phase += bpm * (24.f / 60.f) * (float)frames * (1.f / 48000.f);
    while (m->pulse_phase >= 1.f) {
        m->pulse_phase -= 1.f;
        m->delay.setClockPulse();
        if (++m->pulses % 12 == 0)
            m->delay.setClockEdge();
    }
}

static inline void process48(Munchi *m, float xl, float xr, float *ol, float *orr)
{
    fonepole(m->wet_amt, 1.f, .001f);
    fonepole(m->reverb_amt, m->reverb_amt_target, .001f);
    fonepole(m->reverb_boost, m->reverb_boost_target, .001f);
    float wl = xl * m->wet_amt, wr = xr * m->wet_amt;
    float dl = xl, dr = xr;                         /* the ducking sidechain: the send itself */
    float yl = 0.f, yr = 0.f;
    m->delay.write(wl, wr);
    m->delay.read(&yl, &yr);
    m->reverb.SetAmount(m->reverb_amt * m->reverb_amt * .8f);
    m->reverb.SetTime(m->reverb_amt);
    m->reverb.SetLowpass(m->reverb_amt * .55f + .4f);
    m->reverb.SetDiffusion(m->reverb_amt * .6f);
    yl += wl * m->reverb_boost;
    yr += wr * m->reverb_boost;
    m->reverb.Process(&yl, &yr);
    m->comp.Process(&yl, &yr, &dl, &dr);
    *ol = yl;
    *orr = yr;
}

extern "C" {

/*
 * The state in line 2 if it is Munchi's and still on these lines, else Munchi started afresh: all three lines are
 * cleared when the type changes either way (fresh), and a magic word guards the rest - if anything else ever clears
 * the lines, the next block starts over instead of following zeroed pointers.
 */
void *munchi_ready(void *st, uint32_t st_floats, int16_t *live, uint32_t live_floats, int16_t *frozen, uint32_t frozen_floats,
                   int fresh)
{
    Munchi *m = (Munchi *)st;
    if (fresh || !m || m->magic != MAGIC || m->live != live || m->frozen != frozen)
        m = start(st, st_floats, live, live_floats, frozen, frozen_floats);
    return m;
}

void munchi_block(void *state, const munchi_params *p, float bpm, const float *il, const float *ir, int n,
                  const float **wl, const float **wr)
{
    Munchi *m = (Munchi *)state;
    controls(m, p);
    run_clock(m, bpm, n);
    for (int i = 0; i < n; i++)
        process48(m, il[i], ir[i], &m->wl[i], &m->wr[i]);
    *wl = m->wl;
    *wr = m->wr;
}

}  /* extern "C" */
