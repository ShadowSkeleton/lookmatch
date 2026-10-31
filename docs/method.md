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

## References

- R. E. Barlow, D. J. Bartholomew, J. M. Bremner and H. D. Brunk,
  *Statistical Inference under Order Restrictions*, Wiley, 1972.
  (Isotonic regression.)
- F. N. Fritsch and R. E. Carlson, "Monotone piecewise cubic interpolation,"
  SIAM Journal on Numerical Analysis 17(2), 1980. (PCHIP.)
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
