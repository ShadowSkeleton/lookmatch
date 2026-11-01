"""Generate LIGHTROOM_PROFILE.md with Camera Raw steps.

Lightroom Classic can't load a .cube file directly. A LUT gets into Lightroom
only inside a profile, which Camera Raw (in Photoshop) can make once. The
profile then appears in Lightroom's Profile Browser, with an Amount slider,
and applies the LUT exactly.

The guide is written into each look's folder with the look's own file names,
so the photographer can follow it without looking anything up.
"""

from pathlib import Path

GUIDE_NAME = "LIGHTROOM_PROFILE.md"


def format_guide(name: str, cube_file: str, preset_file: str) -> str:
    """Return the Lightroom profile guide for one look, as Markdown."""
    return f"""# Use "{name}" in Lightroom

You have two ways to use this look in Lightroom Classic or Camera Raw.

| | Profile (recommended) | Preset |
|---|---|---|
| File | `{cube_file}` | `{preset_file}` |
| Accuracy | The full look, exactly as in the report | Tone curve and color tint only |
| Can you edit it? | One Amount slider | Every point of the curves |
| Setup | Once, about 5 minutes, needs Photoshop | Import, about 1 minute |

## The profile: the full look

Lightroom can't open a `.cube` file by itself. Camera Raw, inside
Photoshop, turns it into a profile once. After that, the profile is in
Lightroom like any other.

1. **Open any RAW photo in Photoshop.** It opens in the Camera Raw window.
2. **Set the starting profile.** In the Edit panel, set **Profile** to the
   one your photos were exported with for lookmatch (usually
   **Adobe Color**). Leave every slider at its default.
3. **Open the profile maker.** Open the **Presets** panel (the icon of two
   overlapping circles on the right). Hold **Option** (Mac) or **Alt**
   (Windows) and click the **Create Preset** button (the square with a
   plus). The window that opens is called **Create Profile**.
4. **Fill it in:**
   - **Name:** {name}
   - **Group:** lookmatch
   - Settings: click **None** so nothing else is saved with it.
   - Check **Color Lookup Table**, click **Load Table...**, and pick
     `{cube_file}` from this folder.
   - Under **Advanced Settings**, set **Space** to **sRGB**. This matters:
     lookmatch's LUT works in sRGB, and any other space shifts the colors.
   - Leave **Table Amount** at Min 0 and Max 200.
5. Click **OK**, then **Done**, and close Photoshop.
6. **Restart Lightroom.** The profile is in the **Profile Browser** (click
   the four squares next to Profile in the Basic panel), in the
   **lookmatch** group.

Apply it to a photo whose Profile is the same one you chose in step 2. Then
use the Amount slider to make the look stronger or weaker.

Menus move between versions. If a step doesn't match what you see, don't
guess a setting: the wrong Space shifts every color.

## The preset: curves you can edit

1. In Lightroom's Develop module, open the **Presets** panel on the left.
2. Click the **+** next to Presets, choose **Import Presets...**, and pick
   `{preset_file}`.
3. It appears in the **lookmatch** group.

The preset sets the four point curves in the Tone Curve panel. The main
curve is the look's brightness curve; the red, green and blue curves add its
color tint. It doesn't touch any other slider. Because curves can't express
every color change a LUT makes, the preset is close to the look but not
exact; the report shows the exact look.
"""


def write_guide(
    folder: str | Path, name: str, cube_file: str, preset_file: str
) -> Path:
    """Write LIGHTROOM_PROFILE.md into a look's folder and return its path."""
    path = Path(folder) / GUIDE_NAME
    path.write_text(
        format_guide(name, cube_file, preset_file), encoding="utf-8", newline="\n"
    )
    return path
