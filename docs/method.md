# Method

The math behind lookmatch, with citations. The full write-up is task 8.4;
sections are added here as each part is built.

## Color spaces

lookmatch works in three color spaces:

| Space | Used for | Definition |
|---|---|---|
| sRGB (encoded) | Reading photos, the LUT's input and output | IEC 61966-2-1 transfer function |
| Linear sRGB | Fitting math (light adds up linearly here) | sRGB primaries, D65 white, no transfer function |
| OKLab / OKLCh | Comparing colors the way people see them | Ottosson (2020) |

The sRGB transfer function is applied mirrored around zero, so values slightly
outside [0, 1] that appear during fitting survive a round trip.

OKLab uses the two matrices published by Ottosson. lookmatch computes their
inverses numerically instead of using the rounded published inverses, so a
round trip is exact to float precision. OKLCh is OKLab in polar form: chroma
is the distance from neutral gray, and hue is an angle in degrees.

## Reading photos

- JPEG, PNG and TIFF: an embedded color profile is converted to sRGB with
  LittleCMS (through Pillow). With no profile, sRGB is assumed.
- Camera RAW: decoded by LibRaw (through rawpy) to linear sRGB using the
  camera's white balance, with no auto brightening and no tone curve, then
  encoded to sRGB. White balance and exposure are normalized later anyway.
- Pixel sampling: up to 100,000 pixels per photo, picked at random with a
  fixed seed (0), so the same photo always gives the same sample.

## Neutralize: white balance and exposure

Before measuring a look, lookmatch evens out the light between photos, so the
LUT learns the look and not "this day was cloudy".

**Light color.** Each photo's light is estimated from its pixels in linear
sRGB, ignoring near-black pixels (noise) and pixels with a clipped channel:

- *Gray world* (Buchsbaum 1980): the average color, assuming the scene
  averages to gray.
- *White patch* (Land and McCann 1971): the average color of the brightest
  1% of pixels, assuming the brightest surfaces are white.

Each fails on different scenes. A red canyon fools gray world; a scene with
no white object fools white patch. lookmatch blends them geometrically, half
and half, and scales the result to luminance 1. An estimate whose strongest
channel is more than 4 times its weakest is almost surely scene color, not
light, so it is capped and the photo is flagged as unreliable.

**Exposure.** The median luminance (Rec. 709 weights), which a few very
bright or dark pixels can't move.

**Relative to the group, not to gray.** All reference photos form one group
and all of your photos form another. Each photo is moved to its *group's*
shared light (the geometric mean of the photos' lights) and shared exposure.
This removes the differences between photos but keeps what they share, so a
reference look's overall warmth stays part of the look. A single photo is
left unchanged.

**Gains.** White balance is corrected with per-channel gains in linear sRGB
(the von Kries diagonal model), scaled so a neutral gray keeps its
brightness. Exposure is only corrected halfway, in stops, and at most one
stop. The median can't tell a dark scene from an underexposed one: on the
maintainer's test photos, a full correction pushed a correctly exposed slot
canyon +2.3 stops and a bright sky -1.8 stops.

## Tone curve

The tone curve says how the look maps shadows, midtones and highlights. It is
fitted on OKLab lightness L, pooled from all of your photos and all reference
photos (after neutralizing), in three steps:

1. **Histogram matching.** Each side is summarized by 1000 quantiles, and
   quantile is matched to quantile: the darkest 1% of your photos maps to
   the darkest 1% of the reference, and so on. The photos don't need to show
   the same scene.
2. **Isotonic regression** (Barlow et al. 1972). Repeated values, such as
   many clipped white pixels, can make neighboring pairs disagree. Isotonic
   regression finds the closest curve that never goes down, so a brighter
   input never comes out darker.
3. **PCHIP interpolation** (Fritsch and Carlson 1980). The pairs are averaged
   into about 50 points and joined by a smooth curve that follows their shape
   without overshooting, then sampled at 256 evenly spaced values of L.

Outside the lightness range your photos actually contain, the curve continues
at slope 1 from its ends (no added contrast), clipped to [0, 1].

**Accuracy.** On synthetic photos with a known curve (S-curve, brighter,
darker, faded film, crushed blacks), the largest error is 0.41% of the
lightness range. On a real photo against itself with the test look applied,
it is 0.05%.

**Limitation.** Histogram matching assumes the reference and your photos
contain similar things. If the reference scene is simply brighter (a bright
sky against your canyon), that difference is read as part of the look. On the
maintainer's photos, a bright-sky reference made the fitted curve lift the
midtones to 0.64 where the true look gives 0.50. Pooling several photos on
each side and the "scenes too different" warning exist for this reason.

## Split toning

Split toning is the color tint a look adds at each brightness, like the three
Color Grading wheels in Lightroom (for example teal shadows and warm
highlights). lookmatch models it as an OKLab (a, b) offset that changes
smoothly with lightness L:

    offset(L) = (1 - L)^2 * shadows + 2 L (1 - L) * midtones + L^2 * highlights

The three weights (the quadratic Bernstein basis) are never negative, always
add up to 1, and peak at black, middle gray and white, so the tint blends
smoothly with no visible band between zones.

**Fitting.** The tone curve is applied to your photos first, so both sides
are compared at the brightness they end up at. Both sides are split into 32
lightness bins, and the average (a, b) is taken in each. The difference
between the two sides in each bin is the tint at that brightness. The three
zone offsets are the weighted least squares fit of those differences: bins
with more pixels count more, and a small ridge term keeps a zone with no
pixels (say, no highlights at all) near zero instead of guessing.

**Accuracy.** On synthetic photos with a known teal-and-orange toning, every
offset is recovered within 0.002 OKLab units (about a tenth of a typical
tint). On a real photo against itself with the test look applied, lookmatch
finds the warm shadows and cool highlights the test look adds.

**Limitation.** Like the tone curve, this assumes both sides contain similar
things. With a red canyon as the reference and a different scene as input,
the red rock in the reference's shadows was read as a strong orange shadow
tint. The "scenes too different" warning and pooling several photos are the
defenses; the benchmark will measure how much it matters.

## Residual color: sliced optimal transport

After the tone curve and split toning, some color differences remain, such as
how a look treats particular hues (skies pushed toward teal, greens muted).
Optimal transport moves each of your colors so that the whole set matches the
reference's color distribution, while moving colors as little as possible.

lookmatch uses iterative distribution transfer (Pitié, Kokaram and Dahyot
2007), implemented from the paper. Each of 20 iterations picks a random
rotation of OKLab space, projects both color sets onto the three rotated
axes, matches each axis exactly (in one dimension, optimal transport sends
the k-th smallest value to the same quantile on the other side), and rotates
the moves back. The rotations come from a fixed seed, so the result is
exactly repeatable.

A **strength** from 0 to 1 blends between no change and the full transport.

**Accuracy.** On a synthetic pair with a nonlinear grade, 97% of the color
distribution distance (sliced Wasserstein, measured with the independent POT
library) is removed in about 1 second for 100,000 pixels. Moving a set onto a
shifted copy of itself moves every color by exactly that shift, as optimal
transport should.

On a real photo against itself with the test look, each step closes more of
the gap (distance x100): 1.47 at the start, 0.83 after the tone curve, 0.21
after split toning, 0.01 after transport.

**Limitation, and why strength matters.** Transport makes the distributions
match whether or not the scenes match. With two different scenes, full
strength also drove the distance to almost zero (9.39 to 0.05), which means
forcing one scene's colors into the other's. A matching distribution is not
the same as the right look, so the default strength is chosen with the
benchmark (known looks, measured with ΔE 2000), not by distribution distance.

## Skin tones

Strong looks often push skin toward green, gray or orange, and people notice
skin hue more than any other color. lookmatch finds skin-colored pixels with
a fixed color rule (no AI model), measures how far a look rotates their hue,
and can cap that rotation.

**Skin mask.** A pixel counts as skin when its YCbCr color (ITU-R BT.601,
8-bit) falls in the box 77 ≤ Cb ≤ 127 and 133 ≤ Cr ≤ 173 (Chai and Ngan
1999). lookmatch also skips near-black and near-white pixels (Y below 40 or
above 235), whose color is mostly noise or clipping.

**Hue drift.** The change in OKLCh hue, in degrees, wrapped to ±180°.
Nearly gray pixels (chroma below 0.02) are skipped because their hue swings
wildly with tiny changes. The report gives the mean and 95th percentile.

**Limit (portrait mode only).** With `--portrait`, for skin pixels whose hue
moved more than 6°, the hue is set back to 6° in the same direction, keeping
the look's new lightness and saturation. Without it, skin hue drift is still
measured and shown in the report, with a suggestion to use `--portrait` if
the drift is large and the photos have people.

**Limitation: color alone can't tell skin from skin-colored things.** On the
test chart, only the two ColorChecker skin patches count as skin. But on the
maintainer's desert landscapes, with no people at all, red rock and sand were
counted as skin in 40%, 44% and 68% of the pixels. Capping "skin" hue there
would stop a look from changing the main subject of the photo. A face
detector would fix this, but even classic detectors are trained models,
which lookmatch doesn't use. So the limit is opt-in: you know whether your
photos are portraits; lookmatch can't tell from color alone.

## Baking the LUT

Baking turns the measured look, pairs of "this color in your photos" and
"this color in the look", into the 33 x 33 x 33 LUT your apps load.

The LUT is fitted by sparse least squares. The *prior* P is the LUT made
from the tone curve and split toning alone; the fit looks for a correction
D on top of it, so the final table is T = P + D:

    minimize  (1/N) Σ |A_i T − y_i|²      hit the target colors
            + (λ/n³) |L D|²               keep the correction smooth
            + (μ/n³) |D|²                 keep the correction small

- **A_i** holds the trilinear weights of each sample's 8 surrounding grid
  points: the same interpolation lookmatch, Photoshop and Resolve use to
  read a LUT (task 1.5 showed they agree), so the LUT is fitted exactly the
  way it will be applied.
- **L** is the 3D grid Laplacian (each grid point minus the average of its
  neighbors). Penalizing it stops neighboring colors from jumping, which is
  what shows up as banding.
- **The last term** pulls the correction toward zero, so colors your photos
  never contained fall back to the tone curve plus split toning, not to "no
  change".

The system is symmetric positive definite and is solved with conjugate
gradient in about 1 second, once per channel. Afterwards, outputs are
clipped to sRGB and lightness along the gray axis (black to white) is
checked: it must never go down.

**Choosing the smoothness λ.** Tested on a known look with 60,000 sample
colors, with clean targets and with targets off by about 10 levels of random
noise each (errors in 8-bit levels, for colors the photos contain):

| λ | Clean: 95% / worst | Gray ramp, worst | Noisy: 95% | Roughness vs true look |
|---|---|---|---|---|
| 1.0 | 0.59 / 5.75 | 1.90 | 1.72 | 1.03 x |
| **0.1** | **0.19 / 2.35** | **0.96** | **3.37** | **1.09 x** |
| 0.01 | 0.13 / 1.69 | 0.53 | 6.32 | 1.47 x |
| 0.001 | 0.15 / 4.41 | 0.41 | 9.53 | 2.36 x |

λ = 1 blurs real curvature in the look; λ = 0.01 and below let noise
through and make the LUT rough. lookmatch uses λ = 0.1 and μ = 0.01.

**On a real photo.** The whole chain so far (tone curve, split toning,
transport, bake) run on the maintainer's photo against the same photo with
the test look applied:

| Transport strength | Mean error | 95% of pixels | Worst pixel |
|---|---|---|---|
| 0 | 0.97 | 3.51 | 11.3 |
| 0.5 | 0.53 | 1.82 | 8.5 |
| 1.0 | 0.14 | 0.52 | 4.3 |

(8-bit levels, comparing the baked LUT with the true look on every pixel.)
This is the easy case, the same scene on both sides; the benchmark measures
the hard ones.

## The full pipeline

`lookmatch.pipeline.fit()` runs every step above in order: load and sample
each photo (one at a time, so memory stays low), neutralize each group,
fit the tone curve, split toning and transport on the pooled samples, cap
skin hue in portrait mode, and bake. Every photo contributes the same number
of samples, the total per side is capped at 200,000 so large folders stay
fast, and one fixed seed makes the result exactly repeatable. On small test
photos it takes about 3 seconds.

The transport strength defaults to 0.5. That is a cautious starting value,
not a tuned one: the benchmark will choose it from measured results.

**Results on the maintainer's photos, and the open problem.** The test look
was applied to some photos to make "reference" photos, and the LUT that
lookmatch fitted was compared with the true look on all four photos (mean
error in 8-bit levels; "nothing" means not applying any look):

| Setup | DSC08118 | DSC08255 | DSC08549 | DSC08606 |
|---|---|---|---|---|
| Doing nothing | 7.6 | 7.1 | 5.4 | 7.5 |
| Same 4 scenes on both sides | 4.2 | 2.3 | 1.7 | 2.0 |
| Different scenes on each side | 26.0 | 35.9 | 28.4 | 22.9 |

With the same scenes on both sides, the fitted LUT gets every photo closer to
the true look. With different scenes on each side (references: a cloudy
canyon trail and a dark slot canyon; inputs: a bright desert path and
Horseshoe Bend), it is 3 to 5 times *worse* than doing nothing. The fitted
tone curve took midtones to 0.30 instead of 0.50, because the reference set
contains a dark canyon, and split toning added a strong orange shadow tint
taken from the canyon's red rock. Transport strength made almost no
difference, so the cause is the tone curve and split toning, which compare
distributions and can't tell scene content from the look.

This is the central problem for using other photographers' photos as
references, and it is not solved yet. The next steps are to measure it with
the benchmark (many scenes, known answers) and then to test ways to separate
the look from the scene. Until then, lookmatch works best when the
references and your photos show similar kinds of scenes.

## Baselines

To know whether lookmatch helps, it is compared with simpler methods. Each
one produces a 33-point LUT, so all are judged the same way: applied to
photos, then compared with the true look.

- **No change** (identity LUT). Any method that scores worse than this
  makes photos worse.
- **Reinhard color transfer** (Reinhard et al. 2001), implemented from the
  paper: convert to the l-alpha-beta color space of Ruderman et al. (1998),
  then shift and scale each channel so its mean and spread match the
  reference. The paper doesn't say whether its RGB is linear; lookmatch
  applies the paper's matrix to linear sRGB.
- **Plain optimal transport**: the transport step at full strength on raw
  samples, with no neutralizing, tone curve, split toning or skin step, and
  almost no smoothing (just enough to define colors with no samples).

**First comparison** on the maintainer's 4 photos, with the test look as the
known answer. Mean ΔE 2000 against the true look (below about 1 is
invisible; lower is better):

| Method | Same scenes on both sides | Different scenes on each side |
|---|---|---|
| No change | 3.25 | 3.25 |
| Reinhard | 4.51 | 15.28 |
| Plain optimal transport | **0.35** | 13.44 |
| lookmatch (transport at 0.5) | 1.20 | **11.50** |

Two lessons. With the same scenes, full-strength transport is nearly exact,
and lookmatch's cautious 0.5 strength costs accuracy. With different scenes,
*every* method is far worse than doing nothing; lookmatch is the least bad,
but still harmful. So the cross-scene problem is not a bug in one step: it
is the limit of matching color distributions, shared by the classic methods.
Four photos are too few to tune anything; the benchmark will repeat this on
many scenes and looks.

## References

- R. E. Barlow, D. J. Bartholomew, J. M. Bremner and H. D. Brunk,
  *Statistical Inference under Order Restrictions*, Wiley, 1972.
  (Isotonic regression.)
- F. N. Fritsch and R. E. Carlson, "Monotone piecewise cubic interpolation,"
  SIAM Journal on Numerical Analysis 17(2), 1980. (PCHIP.)
- E. Reinhard, M. Ashikhmin, B. Gooch and P. Shirley, "Color transfer
  between images," IEEE Computer Graphics and Applications 21(5), 2001.
- D. L. Ruderman, T. W. Cronin and C.-C. Chiao, "Statistics of cone
  responses to natural images: implications for visual coding," Journal of
  the Optical Society of America A 15(8), 1998. (l-alpha-beta space.)
- G. Sharma, W. Wu and E. N. Dalal, "The CIEDE2000 color-difference formula:
  implementation notes, supplementary test data, and mathematical
  observations," Color Research and Application 30(1), 2005. (ΔE 2000.)
- F. Pitié, A. Kokaram and R. Dahyot, "Automated colour grading using colour
  distribution transfer," Computer Vision and Image Understanding 107(1-2),
  2007.
- F. Mezzadri, "How to generate random matrices from the classical compact
  groups," Notices of the AMS 54(5), 2007. (Uniform random rotations.)
- D. Chai and K. N. Ngan, "Face segmentation using skin-color map in
  videophone applications," IEEE Transactions on Circuits and Systems for
  Video Technology 9(4), 1999.
- ITU-R BT.601, Studio encoding parameters of digital television. (YCbCr.)
- G. Buchsbaum, "A spatial processor model for object colour perception,"
  Journal of the Franklin Institute 310(1), 1980.
- E. H. Land and J. J. McCann, "Lightness and retinex theory," Journal of the
  Optical Society of America 61(1), 1971.
- J. von Kries, "Chromatic adaptation," 1902. (Diagonal gain model.)
- ITU-R BT.709, Parameter values for the HDTV standards. (Luminance weights.)
- IEC 61966-2-1:1999, Multimedia systems and equipment: Colour measurement
  and management, Part 2-1: Default RGB colour space, sRGB.
- B. Ottosson, "A perceptual color space for image processing," 2020.
  https://bottosson.github.io/posts/oklab/
