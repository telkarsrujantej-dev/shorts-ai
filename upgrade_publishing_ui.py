
from pathlib import Path
from datetime import datetime

root = Path(__file__).resolve().parent
target = root / "frontend" / "index.html"

if not target.exists():
    raise SystemExit("frontend/index.html was not found.")

html = target.read_text(encoding="utf-8")

if "shorts-publishing-upgrade-v1" in html:
    raise SystemExit("Publishing upgrade is already installed.")

for required in [
    'id="navHighlights"',
    'id="libraryPage"',
    'id="libraryList"',
    "</body>",
]:
    if required not in html:
        raise SystemExit(
            f"Missing expected element: {required}. "
            "No changes have been made."
        )

upgrade = r'''
<!-- shorts-publishing-upgrade-v1 -->
<style>
#navDownloads { display:none !important; }
#downloadsPage { display:none !important; }

.publish-toolbar {
  display:flex;gap:10px;align-items:center;
  justify-content:space-between;flex-wrap:wrap;
  padding:15px;margin:16px 0;
  border-radius:13px;background:#F3E9FF;
  border:1px solid #C5A5F2;
}
.publish-toolbar strong { font-size:13px; }
.publish-review {
  margin-top:18px;padding:16px;
  border:1px solid #C5A5F2;
  border-radius:13px;background:#FFFDFB;
}
.publish-review h3{margin:0 0 12px;}
.publish-fields{
  padding:13px;margin-top:12px;
  border:1px solid #DED6CD;border-radius:12px;
}
.publish-fields label{display:block;margin:12px 0 5px}
.publish-fields textarea{
  resize:vertical;min-height:75px;
}
.publish-checkbox {
  display:flex;align-items:center;gap:8px;
  margin:10px 0;font-weight:750;
}
.publish-checkbox input{
  width:18px;height:18px;accent-color:#8353E8;
}
.publish-status{
  font-size:12px;line-height:1.6;
  margin-top:10px;white-space:pre-wrap;
}
.publish-success{color:#287A42}
.publish-error{color:#B72B20}
</style>

<script>
(() => {
  "use strict";

  // Stop using the old automatic publishing controls.
  // Every upload must now come from My Highlights.
  const previousAuto = document.getElementById("autoYoutube");
  if (previousAuto) previousAuto.checked = false;

  const previousUpload =
    document.getElementById("uploadSelectedYouTube");

  if (previousUpload) {
    const oldPanel = previousUpload.closest(".download-box");

    if (oldPanel) {
      oldPanel.hidden = true;

      const heading = oldPanel.previousElementSibling;

      if (
        heading &&
        heading.classList.contains("sidebar-heading")
      ) {
        heading.hidden = true;
      }
    }
  }

  const library = document.getElementById("libraryPage");
  const list = document.getElementById("libraryList");

  const selected = new Map();
  const clipCheckboxes = new Map();

  let clips = [];
  let channel = null;
  let uploading = false;

  const toolbar = document.createElement("div");
  toolbar.className = "publish-toolbar";

  const channelText = document.createElement("div");
  channelText.className = "muted";
  channelText.textContent = "Checking YouTube channel...";

  const selectedText = document.createElement("strong");
  selectedText.textContent = "0 Shorts selected";

  const selectAll = document.createElement("button");
  selectAll.className = "btn small";
  selectAll.textContent = "Select All";

  const clearAll = document.createElement("button");
  clearAll.className = "btn small";
  clearAll.textContent = "Clear";

  const reviewButton = document.createElement("button");
  reviewButton.className = "btn small orange";
  reviewButton.textContent = "Review & Upload";
  reviewButton.disabled = true;

  const controls = document.createElement("div");
  controls.className = "row";
  controls.append(
    selectedText, selectAll, clearAll, reviewButton
  );

  toolbar.append(channelText, controls);
  library.insertBefore(toolbar, list);

  const review = document.createElement("div");
  review.className = "publish-review";
  review.hidden = true;

  const heading = document.createElement("h3");
  heading.textContent = "Review Shorts Before Publishing";

  const privacy = document.createElement("p");
  privacy.className = "muted";
  privacy.textContent =
    "Uploads will be Private. Check each title, " +
    "description and audience before confirming.";

  const reviewRows = document.createElement("div");

  const confirmUpload = document.createElement("button");
  confirmUpload.className = "primary";
  confirmUpload.textContent = "Confirm & Upload Selected Shorts";

  const resultText = document.createElement("div");
  resultText.className = "publish-status";
  resultText.setAttribute("role", "status");

  review.append(
    heading, privacy, reviewRows,
    confirmUpload, resultText
  );

  list.after(review);

  function button(text, action) {
    const element = document.createElement("button");
    element.className = "btn small lilac";
    element.textContent = text;
    element.onclick = action;
    return element;
  }

  function refreshCount() {
    selectedText.textContent =
      selected.size + " Shorts selected";

    reviewButton.disabled =
      !selected.size || !channel || uploading;

    review.hidden = true;
  }

  function changeSelection(clip, checked) {
    if (checked && selected.size >= 6 &&
        !selected.has(clip.filename)) {
      message(
        "libraryStatus",
        "Select up to six Shorts per upload.",
        "error"
      );

      const checkbox = clipCheckboxes.get(clip.filename);
      if (checkbox) checkbox.checked = false;
      return;
    }

    if (checked) selected.set(clip.filename, clip);
    else selected.delete(clip.filename);

    refreshCount();
  }

  selectAll.onclick = () => {
    selected.clear();

    clips.forEach((clip, index) => {
      const checked = index < 6;

      if (checked) selected.set(clip.filename, clip);

      const checkbox = clipCheckboxes.get(clip.filename);
      if (checkbox) checkbox.checked = checked;
    });

    refreshCount();
  };

  clearAll.onclick = () => {
    selected.clear();

    for (const checkbox of clipCheckboxes.values()) {
      checkbox.checked = false;
    }

    refreshCount();
  };

  function makeLabel(text, control) {
    const wrapper = document.createElement("label");
    wrapper.textContent = text;
    wrapper.append(control);
    return wrapper;
  }

  function makeOption(value, text) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    return option;
  }

  const reviewData = new Map();

  reviewButton.onclick = () => {
    reviewRows.replaceChildren();
    reviewData.clear();
    resultText.textContent = "";

    for (const clip of selected.values()) {
      const row = document.createElement("div");
      row.className = "publish-fields";

      const title = document.createElement("input");
      title.className = "input";
      title.maxLength = 100;
      title.value = (clip.title || "My Short").slice(0,100);

      const description = document.createElement("textarea");
      description.className = "input";
      description.maxLength = 5000;
      description.value = "";

      const audience = document.createElement("select");
      audience.className = "input";
      audience.append(
        makeOption("", "Select audience"),
        makeOption("no", "Not made for kids"),
        makeOption("yes", "Made for kids")
      );

      const name = document.createElement("strong");
      name.textContent = clip.filename;

      const status = document.createElement("p");
      status.className = "publish-status";

      row.append(
        name,
        makeLabel("Video title", title),
        makeLabel("Description", description),
        makeLabel("Audience", audience),
        status
      );

      reviewRows.append(row);

      reviewData.set(clip.filename, {
        clip, title, description, audience, status
      });
    }

    review.hidden = false;
    review.scrollIntoView({
      behavior: "smooth",
      block: "start"
    });
  };

  function showGallery(items, uploaded) {
    list.replaceChildren();
    clipCheckboxes.clear();

    const uploadedNames = new Set(
      uploaded.map(item => item.filename)
    );

    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No generated Shorts found.";
      list.append(empty);
      return;
    }

    for (const clip of items) {
      const url = safeClipURL(clip);
      if (!url) continue;

      const card = document.createElement("div");
      card.className = "video-card";

      const video = document.createElement("video");
      video.src = url;
      video.preload = "metadata";
      video.muted = true;
      video.playsInline = true;

      const title = document.createElement("strong");
      title.textContent = clip.title || clip.filename;

      const label = document.createElement("label");
      label.className = "publish-checkbox";

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";

      const text = document.createElement("span");
      text.textContent = "Select for YouTube";

      label.append(checkbox,text);

      checkbox.onchange = () => {
        changeSelection(clip, checkbox.checked);
      };

      clipCheckboxes.set(clip.filename, checkbox);

      const preview = button(
        "▶ Preview Short",
        () => selectDownload(clip)
      );

      card.append(video,title,label,preview);

      if (uploadedNames.has(clip.filename)) {
        const badge = document.createElement("p");
        badge.className = "publish-status publish-success";
        badge.textContent = "✓ Previously uploaded to YouTube";
        card.append(badge);
      }

      list.append(card);
    }
  }

  async function loadPublishingGallery() {
    selected.clear();
    clipCheckboxes.clear();
    review.hidden = true;
    channel = null;
    refreshCount();

    channelText.textContent =
      "Checking your authorized YouTube channel...";

    message("libraryStatus", "Loading your Highlights...");

    try {
      const data = await api("/workflow/gallery");
      clips = (data.items || []).filter(safeClipURL);

      let history = [];

      try {
        const uploadData = await api("/publish/history");
        history = uploadData.items || [];
      } catch {
        // Highlights remain usable if history is unavailable.
      }

      showGallery(clips, history);
      message("libraryStatus", "");

    } catch (error) {
      message("libraryStatus", error.message, "error");
    }

    try {
      const data = await api("/publish/channel");

      if (!data.connected) {
        throw new Error(
          data.reason || "No YouTube channel connected."
        );
      }

      channel = data;

      channelText.textContent =
        "✓ Connected: " + data.channel_name +
        " (" + data.channel_id + ")";

    } catch (error) {
      channel = null;

      channelText.textContent =
        "YouTube not connected: " + error.message;
    }

    refreshCount();
  }

  confirmUpload.onclick = async () => {
    if (uploading || !channel || !reviewData.size) return;

    const jobs = [];

    for (const data of reviewData.values()) {
      const title = data.title.value.trim();
      const audience = data.audience.value;

      if (!title || !audience) {
        resultText.textContent =
          "Every Short needs a title and audience selection.";
        return;
      }

      jobs.push({
        ...data,
        titleValue: title,
        descriptionValue: data.description.value,
        madeForKids: audience === "yes"
      });
    }

    // Verify the channel again before any upload.
    try {
      const current = await api("/publish/channel");

      if (!current.connected ||
          current.channel_id !== channel.channel_id) {
        throw new Error(
          "Your connected YouTube channel changed."
        );
      }
    } catch (error) {
      resultText.textContent = error.message;
      return;
    }

    if (!confirm(
      "Upload " + jobs.length +
      " selected Shorts to " + channel.channel_name +
      " as PRIVATE videos?"
    )) return;

    uploading = true;
    confirmUpload.disabled = true;
    selectAll.disabled = true;
    clearAll.disabled = true;

    let succeeded = 0;
    let failed = 0;

    for (const job of jobs) {
      job.status.textContent = "Uploading...";

      try {
        const response = await api(
          "/publish/upload-one",
          requestOptions("POST", {
            filename: job.clip.filename,
            channel_id: channel.channel_id,
            title: job.titleValue,
            description: job.descriptionValue,
            made_for_kids: job.madeForKids
          })
        );

        succeeded++;
        job.status.className =
          "publish-status publish-success";

        job.status.textContent =
          response.already_uploaded
            ? "Already uploaded: " + response.youtube_url
            : "✓ Uploaded: " + response.youtube_url;

      } catch (error) {
        failed++;
        job.status.className =
          "publish-status publish-error";
        job.status.textContent =
          "Upload failed: " + error.message;
      }
    }

    uploading = false;
    confirmUpload.disabled = false;
    selectAll.disabled = false;
    clearAll.disabled = false;

    resultText.textContent =
      succeeded + " successful or previously uploaded, " +
      failed + " failed. Check YouTube Studio " +
      "before retrying an uncertain upload.";

    refreshCount();

    // Keep the review results visible.
    review.hidden = false;
  };

  // Replace only the old My Highlights navigation action.
  document.getElementById("navHighlights").onclick =
    async () => {
      showPage("library");
      await loadPublishingGallery();
    };

})();
</script>
'''

backup = target.with_name(
    "index_before_publishing_" +
    datetime.now().strftime("%Y%m%d_%H%M%S") +
    ".html"
)

updated = html.replace("</body>", upgrade + "\n</body>", 1)

# No partial editing: write backup before replacing.
backup.write_text(html, encoding="utf-8")
target.write_text(updated, encoding="utf-8")

print("My Highlights publishing interface installed.")
print("Backup:", backup)
print("Updated:", target)
