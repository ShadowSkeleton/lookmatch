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

## References

- IEC 61966-2-1:1999, Multimedia systems and equipment: Colour measurement
  and management, Part 2-1: Default RGB colour space, sRGB.
- B. Ottosson, "A perceptual color space for image processing," 2020.
  https://bottosson.github.io/posts/oklab/
