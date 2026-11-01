# Using your look in editing apps

Each lookmatch look comes as a few files, because apps read looks in
different ways. Pick your app below and use the file it names.

| File | What it is | Use it in |
|---|---|---|
| `NAME_33.cube` | The look as a LUT, exact | Photoshop, DaVinci Resolve, Affinity Photo, darktable, Lightroom (as a profile) |
| `NAME_hald.png` | The same LUT stored as an image | RawTherapee, darktable, ImageMagick |
| `NAME_preset.xmp` | Tone curve and color tint as editable curves, close but not exact | Lightroom Classic, Camera Raw |
| `LIGHTROOM_PROFILE.md` | Steps to turn the LUT into a Lightroom profile | Lightroom Classic |

**Apply the look to photos rendered the way lookmatch saw them.** The LUT
learned from your unedited photos, so apply it before other color edits, with
the same camera profile you exported with. You can adjust exposure and white
balance first; then add the look, then fine-tune.

**Checked apps.** For Photoshop and DaVinci Resolve, a test measured the
result against lookmatch's own: Photoshop matches pixel for pixel, Resolve
within 1 level out of 255 (invisible). The other apps below haven't been
measured yet; their steps follow each app's documentation.

| App | File | Checked |
|---|---|---|
| [Photoshop](#photoshop) | `.cube` | Yes, identical |
| [DaVinci Resolve](#davinci-resolve) | `.cube` | Yes, within 1 level |
| [Lightroom Classic](#lightroom-classic-and-camera-raw) | profile from `.cube`, or `.xmp` preset | Not yet |
| [Camera Raw](#lightroom-classic-and-camera-raw) | profile from `.cube`, or `.xmp` preset | Not yet |
| [Affinity Photo](#affinity-photo) | `.cube` | Not yet |
| [RawTherapee](#rawtherapee) | `_hald.png` | Not yet |
| [darktable](#darktable) | `.cube` or `_hald.png` | Not yet |
| [ImageMagick](#imagemagick) | `_hald.png` | Yes, within 1 level for 99% of pixels |

---

## Photoshop

1. Open your photo.
2. **Layer > New Adjustment Layer > Color Lookup...**, then OK.
3. In the **Properties** panel, open the menu next to **3DLUT File**, choose
   **Load 3D LUT...**, and pick `NAME_33.cube`.
4. Lower the layer's **Opacity** for a weaker look.

If an **Embedded Profile Mismatch** box appears when you open a photo,
choose **Use the embedded profile**. The LUT expects sRGB photos; for a
photo in another color space (for example Adobe RGB), first use
**Edit > Convert to Profile... > sRGB**.

## DaVinci Resolve

1. **Project Settings > Color Management:** keep **DaVinci YRGB** and set
   **3D lookup table interpolation** to **Trilinear**.
2. In the same tab, click **Open LUT Folder**, copy `NAME_33.cube` into it,
   then click **Update Lists**.
3. On the **Color** page, right-click a node > **LUT** > pick the look.

For photos (stills), right-click the clip in the Media Pool >
**Clip Attributes... > Data Levels: Full**, so the LUT sees the full range.

## Lightroom Classic and Camera Raw

Two choices. Both are explained step by step in `LIGHTROOM_PROFILE.md`,
which lookmatch writes next to your look with the right file names in it.

- **Profile (recommended): the exact look.** Camera Raw, inside Photoshop,
  turns `NAME_33.cube` into a profile once (about 5 minutes). It then
  appears in Lightroom's Profile Browser with an Amount slider. The one
  setting that must be right: the table's **Space** is **sRGB**.
- **Preset: editable, close but not exact.** Import `NAME_preset.xmp` in the
  Develop module's **Presets** panel (**+ > Import Presets...**). It sets the
  four point curves in the Tone Curve panel: the main curve is the look's
  brightness curve, and the red, green and blue curves add its color tint.
  Nothing else changes. Curves can't make every color change a LUT makes,
  so saturated colors can come out slightly different from the report.

In Camera Raw, the profile works the same way. To import the preset, open
the **Presets** panel, click the **...** menu, and choose
**Import Profiles & Presets...**.

## Affinity Photo

1. **Layer > New Adjustment > LUT**.
2. Click **Load LUT...** and pick `NAME_33.cube`.

Affinity applies the LUT in the document's color space. Use an sRGB
document (**Document > Convert Format / ICC Profile...**).

## RawTherapee

RawTherapee calls a Hald image a film simulation.

1. Make a folder for your looks and copy `NAME_hald.png` into it.
2. **Preferences > Image Processing > Film Simulation > Directory:** pick
   that folder, then restart RawTherapee.
3. In the **Color** tab, turn on **Film Simulation** and pick the look.
   **Strength** makes it weaker.

## darktable

1. **Preferences > processing > LUT 3D root folder:** pick a folder, and copy
   `NAME_33.cube` (or `NAME_hald.png`) into it.
2. In the darkroom, turn on the **lut 3D** module and pick the file.
3. Set **application color space** to **sRGB**: lookmatch's LUT works in
   sRGB.

## ImageMagick

For applying a look to many photos from the command line:

```bash
magick photo.jpg NAME_hald.png -hald-clut photo_with_look.jpg
```

This writes a new file and leaves `photo.jpg` unchanged.

---

## If the look comes out different

- **Wrong color space.** Every lookmatch file expects sRGB photos and
  produces sRGB. Most problems come from an app applying the LUT in another
  space (Adobe RGB, ProPhoto RGB, Rec.709 video, or linear).
- **Edited before the look.** Strong edits before the LUT (contrast,
  saturation, another profile) change what the LUT starts from.
- **RAW photos decoded by lookmatch.** If lookmatch decoded your RAW files
  itself, your editor renders them a little differently, so the look may be
  slightly off there. Exports from your editor give the most accurate look
  (see the warning in `report.html`).
