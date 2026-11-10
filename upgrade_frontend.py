
from pathlib import Path
from datetime import datetime
import os

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "frontend" / "index.html"

if not TARGET.is_file():
    raise SystemExit(
        "Cannot find frontend/index.html. "
        "Run this script from the project containing your dashboard."
    )

original = TARGET.read_text(encoding="utf-8")
html = original

if 'id="exportMP3"' in html:
    raise SystemExit(
        "The MP3 interface is already present. "
        "This updater will not apply changes twice."
    )


def replace_once(old, new, description):
    global html

    count = html.count(old)

    if count != 1:
        raise SystemExit(
            f"Stopped safely: {description}. "
            f"Expected one match, found {count}. "
            "Your original file has not been modified."
        )

    html = html.replace(old, new, 1)


# ==================================================
# 1. IMPROVE LAYOUT, KEEP RESPONSIVE DESIGN
# ==================================================

css = r"""
/* Creator Studio upgrades */

@media (min-width: 1151px) {
    .layout {
        max-width: 1800px;
        grid-template-columns:
            245px minmax(0, 1fr) 395px;
    }
}

@media (min-width: 701px) and (max-width: 1150px) {
    .layout {
        grid-template-columns:
            220px minmax(0, 1fr);
    }

    .preview-column {
        grid-column: 2;
        position: static;
    }

    .video-stage {
        aspect-ratio: 16 / 9;
        max-height: 460px;
    }
}

@media (max-width: 700px) {
    .layout {
        display: flex;
        flex-direction: column;
    }

    .video-stage {
        aspect-ratio: 9 / 16;
        max-height: 550px;
    }
}

@media (min-width: 1151px) {
    .video-stage {
        aspect-ratio: 9 / 16;
    }
}

.video-stage video {
    width: 100%;
    height: 100%;
    object-fit: contain;
}

.sidebar .download-box {
    margin-bottom: 14px;
}

.creator-checkbox {
    display: flex;
    align-items: flex-start;
    gap: 9px;
    margin-top: 14px;
    line-height: 1.5;
    font-size: 12px;
}

.creator-checkbox input {
    margin-top: 3px;
    accent-color: #8353E8;
}
"""

replace_once(
    "</style>",
    css + "\n</style>",
    "Adding improved styles"
)


# ==================================================
# 2. ADD MP3 STUDIO AND YOUTUBE STUDIO
# ==================================================

sidebar_html = r"""
    <!-- SEPARATE MP3 STUDIO -->
    <div class="sidebar-heading">MP3 STUDIO</div>

    <div class="download-box">
      <h3>♫ Audio Export</h3>

      <p class="muted">
        Extract MP3 audio from your selected Short.
        This is separate from MP4 Downloads.
      </p>

      <button
        id="exportMP3"
        class="btn small lilac"
        style="width:100%"
        type="button"
      >
        ♫ Export Selected MP3
      </button>

      <div id="mp3Status" class="status" role="status"></div>
    </div>

    <!-- SEPARATE YOUTUBE STUDIO -->
    <div class="sidebar-heading">YOUTUBE STUDIO</div>

    <div class="download-box">
      <h3>▶ YouTube Upload</h3>

      <p id="youtubeConnection" class="muted">
        Checking YouTube connection...
      </p>

      <label for="youtubeAudience">Video audience</label>

      <select id="youtubeAudience" class="input">
        <option value="">Select audience</option>
        <option value="no">Not made for kids</option>
        <option value="yes">Made for kids</option>
      </select>

      <p class="muted">
        Uploads will initially be Private.
        Select the appropriate audience.
      </p>

      <button
        id="uploadSelectedYouTube"
        class="btn orange"
        style="width:100%;margin-top:10px"
        type="button"
      >
        ▶ Upload Selected Short
      </button>

      <label class="creator-checkbox">
        <input type="checkbox" id="autoYoutube">
        <span>
          Automatically upload newly generated
          Shorts to my connected YouTube channel
          as Private videos.
        </span>
      </label>

      <div id="youtubeStatus"
           class="status"
           role="status"></div>
    </div>

"""

replace_once(
    '    <div class="sidebar-note">',
    sidebar_html + '    <div class="sidebar-note">',
    "Adding MP3 and YouTube Studio"
)


# ==================================================
# 3. TRACK ACTUAL MP4 DOWNLOAD REQUESTS
# ==================================================

replace_once(
    '$("downloadLink").href = url;',
    '''$("downloadLink").href =
    "/creator/download/" +
    encodeURIComponent(clip.filename);''',
    "Connecting MP4 download history"
)


# ==================================================
# 4. DIFFERENTIATE DOWNLOADS AND MY HIGHLIGHTS
# ==================================================

replace_once(
    'const data = await api("/workflow/gallery");',
    '''const endpoint =
      target === $("downloadsList")
        ? "/creator/downloads"
        : "/workflow/gallery";

    const data = await api(endpoint);''',
    "Separating the Downloads library"
)


# ==================================================
# 5. USE TRANSCRIPT-ASSISTED GEMINI ANALYSIS
# ==================================================

replace_once(
    '"/highlights/" +',
    '"/creator/analyze/" +',
    "Connecting improved Gemini analysis"
)


# ==================================================
# 6. OPTIONAL AUTOMATIC YOUTUBE UPLOADS
# ==================================================

replace_once(
    "state.outputs = data.clips;",
    """state.outputs = data.clips;

  // Optional, explicitly enabled private YouTube upload.
  // Never interrupt video generation if YouTube fails.
  if ($("autoYoutube").checked) {
    void autoUploadGeneratedShorts(data.clips);
  }""",
    "Connecting automatic YouTube uploads"
)


# ==================================================
# 7. MP3 + YOUTUBE JAVASCRIPT
# ==================================================

javascript = r"""

/* ================================================
   CREATOR FEATURES
   Separate MP3, Downloads, and YouTube Studio
================================================ */

const youtubeUploadedThisSession = new Set();
let youtubeConnected = false;


/* MP3 AUDIO EXPORT */

$("exportMP3").onclick = async () => {
  const clip = state.selectedOutput;

  if (!clip || !safeClipURL(clip)) {
    message(
      "mp3Status",
      "Select a generated Short first.",
      "error"
    );
    return;
  }

  const button = $("exportMP3");
  button.disabled = true;

  message("mp3Status", "Converting the selected Short...");

  try {
    const response = await fetch(
      "/creator/mp3/" +
      encodeURIComponent(clip.filename)
    );

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));

      throw new Error(
        data.detail || "MP3 export failed."
      );
    }

    const blob = await response.blob();
    const objectURL = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = objectURL;
    link.download = clip.filename.replace(
      /\.mp4$/i,
      ".mp3"
    );

    document.body.appendChild(link);
    link.click();
    link.remove();

    setTimeout(
      () => URL.revokeObjectURL(objectURL),
      10000
    );

    message(
      "mp3Status",
      "MP3 download started.",
      "success"
    );

  } catch (error) {
    message("mp3Status", error.message, "error");
  } finally {
    button.disabled = false;
  }
};


/* YOUTUBE CONNECTION STATUS */

async function refreshYouTubeConnection() {
  try {
    const data = await api(
      "/creator/youtube/status"
    );

    youtubeConnected = Boolean(data.connected);

    $("youtubeConnection").textContent =
      youtubeConnected
        ? "✓ YouTube account connected"
        : "YouTube not connected. Run connect_youtube.py.";

  } catch {
    youtubeConnected = false;

    $("youtubeConnection").textContent =
      "YouTube backend unavailable. Check creator_features.py.";
  }
}


/* CHECK VIDEO AUDIENCE */

function getYouTubeAudience() {
  const selected = $("youtubeAudience").value;

  if (!selected) {
    throw new Error(
      "Select whether your video is made for kids."
    );
  }

  return selected === "yes";
}


/* UPLOAD ONE MP4 TO YOUTUBE */

async function uploadShortToYouTube(clip) {
  if (!safeClipURL(clip)) {
    throw new Error("Select a valid generated MP4 Short.");
  }

  if (!youtubeConnected) {
    throw new Error(
      "Connect your YouTube account first."
    );
  }

  const madeForKids = getYouTubeAudience();

  return api(
    "/creator/youtube/upload/" +
      encodeURIComponent(clip.filename),

    requestOptions("POST", {
      title: String(
        clip.title || "Shorts AI Video"
      ).trim().slice(0, 100),

      description:
        "Created using the Shorts AI Video Editing Agent.",

      made_for_kids: madeForKids
    })
  );
}


/* MANUAL YOUTUBE UPLOAD BUTTON */

$("uploadSelectedYouTube").onclick = async () => {
  const clip = state.selectedOutput;

  if (!clip) {
    message(
      "youtubeStatus",
      "Select a generated Short first.",
      "error"
    );
    return;
  }

  const button = $("uploadSelectedYouTube");
  button.disabled = true;

  message(
    "youtubeStatus",
    "Uploading your Short privately to YouTube..."
  );

  try {
    const result = await uploadShortToYouTube(clip);

    youtubeUploadedThisSession.add(clip.filename);

    message(
      "youtubeStatus",
      "Successfully uploaded as Private:\n" +
      result.youtube_url,
      "success"
    );

  } catch (error) {
    message(
      "youtubeStatus",
      error.message,
      "error"
    );

    // Refresh status in case the OAuth token expired.
    await refreshYouTubeConnection();
  } finally {
    button.disabled = false;
  }
};


/* EXPLICIT OPT-IN FOR AUTOMATIC UPLOADS */

$("autoYoutube").onchange = async function () {
  if (!this.checked) return;

  try {
    await refreshYouTubeConnection();

    if (!youtubeConnected) {
      throw new Error(
        "Connect YouTube before enabling automatic uploads."
      );
    }

    getYouTubeAudience();

    const approved = confirm(
      "Automatically upload newly generated Shorts " +
      "as PRIVATE videos to your connected YouTube channel?"
    );

    if (!approved) {
      this.checked = false;
    }

  } catch (error) {
    this.checked = false;

    message(
      "youtubeStatus",
      error.message,
      "error"
    );
  }
};


/* AUTOMATIC PRIVATE UPLOAD AFTER GENERATION */

async function autoUploadGeneratedShorts(clips) {
  if (!$("autoYoutube").checked) return;

  try {
    getYouTubeAudience();

    if (!youtubeConnected) {
      throw new Error(
        "YouTube is not connected."
      );
    }

  } catch (error) {
    message(
      "youtubeStatus",
      error.message,
      "error"
    );
    return;
  }

  let completed = 0;
  let skipped = 0;
  const errors = [];

  for (const clip of clips) {
    if (!clip || !safeClipURL(clip)) continue;

    // Avoid duplicate uploads from repeat renders
    // during this browser session.
    if (youtubeUploadedThisSession.has(clip.filename)) {
      skipped++;
      continue;
    }

    // Reserve the filename before uploading.
    youtubeUploadedThisSession.add(clip.filename);

    message(
      "youtubeStatus",
      "Uploading Short " +
      (completed + skipped + 1) +
      " of " + clips.length + "..."
    );

    try {
      await uploadShortToYouTube(clip);
      completed++;

    } catch (error) {
      youtubeUploadedThisSession.delete(clip.filename);

      errors.push(
        (clip.title || clip.filename) +
        ": " + error.message
      );
    }
  }

  if (errors.length) {
    message(
      "youtubeStatus",
      completed + " uploaded, " +
      errors.length + " failed.\n" +
      errors.join("\n"),
      "error"
    );
  } else {
    message(
      "youtubeStatus",
      completed + " new Shorts uploaded privately." +
      (skipped ? " " + skipped + " already uploaded." : ""),
      "success"
    );
  }
}


/* CHECK CONNECTION AT PAGE LOAD */

refreshYouTubeConnection();

"""

replace_once(
    "\nupdateUndo();\ndrawStage();\n</script>",
    "\n" + javascript +
    "\nupdateUndo();\ndrawStage();\n</script>",
    "Connecting creator feature buttons"
)


# ==================================================
# 8. VERIFY AND SAVE SAFELY
# ==================================================

required_markers = [
    'id="exportMP3"',
    'id="youtubeAudience"',
    'id="uploadSelectedYouTube"',
    'id="autoYoutube"',
    '"/creator/downloads"',
    '"/creator/analyze/"',
    '"/creator/mp3/"',
    '"/creator/youtube/upload/"',
]

for marker in required_markers:
    if marker not in html:
        raise SystemExit(
            "Validation failed: " + marker +
            ". Original HTML was not changed."
        )

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

backup = TARGET.with_name(
    "index_before_creator_update_" +
    timestamp + ".html"
)

backup.write_text(original, encoding="utf-8")

temporary = TARGET.with_name(
    "index_creator_upgrade.tmp"
)

try:
    temporary.write_text(html, encoding="utf-8")
    os.replace(temporary, TARGET)

finally:
    temporary.unlink(missing_ok=True)

print()
print("SUCCESS: Shorts AI frontend upgraded!")
print("Updated:", TARGET)
print("Backup:", backup)
print()
print("Included:")
print("  1. Separate MP4 download history")
print("  2. Independent MP3 Studio")
print("  3. YouTube Studio")
print("  4. Optional automatic private uploads")
print("  5. Transcript-assisted Gemini route")
print("  6. Larger responsive video preview")
print()
print("Restart FastAPI and refresh /dashboard.")
