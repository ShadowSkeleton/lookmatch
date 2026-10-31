# App check: does a lookmatch LUT look the same everywhere?

This is task 1.5, and it needs a person with the apps open. It takes about
30 minutes the first time.

**What you're checking:** lookmatch writes `.cube` LUT files. Before building
anything clever on top, we need proof that Photoshop and DaVinci Resolve apply
that LUT exactly the way lookmatch does. If they don't, every look lookmatch
makes later would come out slightly wrong in your apps.

**How:** you open one test image in each app, apply one test LUT, and save the
result. A script then measures 69 color patches in each saved image and
compares them with lookmatch's own result.

**Goal:** every patch within 2 levels (out of 255). That difference is
invisible.

---

## Step 1. Find the two files

Everything is in the folder **`lookmatch-qa`** on your Desktop:

| File | What it is |
|---|---|
| `test_chart.png` | The test image: a gray ramp, 24 ColorChecker patches, pure colors |
| `test_look_33.cube` | The test LUT: warmer shadows, cooler highlights |

You'll save your results into the same folder.

(The originals live in the repo at `tests/fixtures/`. If the Desktop folder
is missing, copy those two files into a new `lookmatch-qa` folder.)

---

## Step 2. Photoshop (about 5 minutes)

1. **Open the chart.** File > Open > `lookmatch-qa/test_chart.png`.
   - If a box called **Embedded Profile Mismatch** appears, choose
     **Use the embedded profile (instead of the working space)**, then OK.
     This keeps the colors exactly as they are in the file.
2. **Check the mode.** Open the Image > Mode menu. **RGB Color** and
   **8 Bits/Channel** should both have a check mark. If not, click them.
3. **Add the LUT.** Layer > New Adjustment Layer > **Color Lookup...**, then OK.
4. **Load the file.** In the **Properties** panel (Window > Properties if you
   can't see it), click the menu next to **3DLUT File** and choose
   **Load 3D LUT...**. Pick `lookmatch-qa/test_look_33.cube`.
   - The shadows should turn slightly warm and the highlights slightly cool.
   - If the Properties panel has a **Dither** checkbox, **uncheck it**.
     Dither adds tiny random noise, which would blur the measurement.
5. **Save a copy.** File > **Save a Copy...**
   - Format: **PNG**
   - Name: **`photoshop.png`**, in the `lookmatch-qa` folder
   - If there's an option to embed the color profile, leave it on.
   - In PNG Options, the defaults are fine. Click OK.
6. Don't resize or crop anything. You can close the file without saving.

---

## Step 3. DaVinci Resolve (about 20 minutes, including the download)

Resolve is free. You only need the free version, not Studio.

### Install

1. Go to **blackmagicdesign.com/products/davinciresolve** and click
   **Free Download**. Choose **DaVinci Resolve** (not Studio) for **Mac OS X**.
2. It asks for a short registration form. Fill it in and download.
3. Open the downloaded file and run the installer.

### Set up a project

1. Open Resolve. In the Project Manager, click **New Project**, name it
   **lookmatch qa**, and click Create.
2. Open **Project Settings**: the gear icon at the bottom right.
3. **Master Settings** tab:
   - **Timeline resolution:** choose **Custom**, then type **1280** x **1020**.
4. **Image Scaling** tab:
   - **Mismatched resolution files:** **Center crop with no resizing**.
5. **Color Management** tab:
   - **Color science:** **DaVinci YRGB** (the default).
   - **Timeline color space:** **Rec.709 Gamma 2.4** (the default).
   - **3D lookup table interpolation:** **Trilinear**.
6. Still in **Color Management**, find **Lookup Tables** and click
   **Open LUT Folder**. A Finder window opens. Copy `test_look_33.cube` into
   it. Back in Resolve, click **Update Lists**.
7. Click **Save** at the bottom of Project Settings.

### Apply the LUT

1. Go to the **Media** page (tabs along the bottom of the window).
   Drag `test_chart.png` from Finder into the **Media Pool**.
2. Right-click the chart in the Media Pool > **Clip Attributes...** >
   **Data Levels:** **Full**, then OK.
3. Go to the **Edit** page and drag the chart onto the timeline.
   - If Resolve asks to change the project settings to match the clip,
     choose **Don't Change**.
4. Go to the **Color** page. In the node area (top right) there is one node,
   labeled **01**. Right-click it > **LUT** > find and pick **test_look_33**.
   The chart's shadows should turn slightly warm.

### Save the result

1. Right-click the image in the viewer > **Grab Still**.
2. Click **Gallery** (top left of the Color page) to see the still.
3. Right-click the still > **Export...**
   - Format: **PNG**
   - Name: **`resolve`**, in the `lookmatch-qa` folder. Resolve 21 makes a
     folder called `resolve` and saves the image inside it as something like
     `default_1.1.1.png` (plus a `.drx` grade file you can ignore). That's fine.

---

## Step 4. Run the check

The easiest way: tell Claude **"the exports are ready"**, and Claude runs it.

To run it yourself, open Terminal and paste:

```bash
cd ~/Desktop/lookmatch && .venv/bin/python bench/app_check.py Photoshop=~/Desktop/lookmatch-qa/photoshop.png Resolve=~/Desktop/lookmatch-qa/resolve/default_1.1.1.png
```

(Use the real file name Resolve gave the image.)

The latest results are in [bench/APP_CHECK_RESULTS.md](../bench/APP_CHECK_RESULTS.md).

---

## Step 5. Read the result

Each app gets one verdict:

| Verdict | Meaning | What to do |
|---|---|---|
| **PASS** | Every patch within 2 levels | Nothing. That app matches lookmatch. |
| **CLOSE** | Within 4 levels | Hard to see, but worth a look. Send it to Claude. |
| **FAIL** | Some patches clearly differ | Usually a color management setting. Send it to Claude. |
| **NOT APPLIED** | The export looks like the original chart | The LUT was off when you saved. Redo the last steps. |
| **WRONG SIZE** | The export isn't 1280 x 1020 | The app resized it. Check the resolution and scaling settings. |

The report also lists the 5 most different patches, which usually shows
the cause: if only the gray ramp is off, it's a tone setting; if only the
saturated colors are off, it's a gamut or color space setting.

---

## Why not Lightroom Classic?

Lightroom Classic can't load a `.cube` file directly. A LUT gets into
Lightroom only inside a **profile**, made once with Camera Raw. That's task
5.3, where we'll do the same kind of check for Lightroom.

## If something looks different

Menus move between app versions. If a step doesn't match what you see, take a
screenshot and send it to Claude. Don't guess a setting: a wrong color
setting is exactly what this test is trying to catch.
