
from pathlib import Path
from datetime import datetime

# Run this script from your project root.
path = Path("frontend/index.html")

if not path.exists():
    raise SystemExit(
        "frontend/index.html not found. "
        "Run this script from your project folder."
    )

source = path.read_text(encoding="utf-8-sig")

# Keep the original working editor, video, subtitles,
# Gemini integration and YouTube publishing functions.
marker = "<!-- shorts-publishing-upgrade-v1 -->"

if marker not in source:
    raise SystemExit(
        "Expected publishing marker not found. "
        "No changes were made."
    )

marker_pos = source.index(marker)
base = source[:marker_pos]

publisher_start = source.index("<script>", marker_pos)
publisher_end = source.index(
    "</script>", publisher_start
) + len("</script>")

publishing_script = source[
    publisher_start:publisher_end
]

# Everything following the publishing script consists
# of overlapping UI changes. We replace those with
# one consolidated design and navigation layer.

css = r"""
<style>
/* SHORTS AI — CLEAN REFERENCE DESIGN */

:root {
  --bg: #fff8f0;
  --paper: #fffefa;
  --ink: #242125;
  --muted: #807777;
  --line: #f0dfcf;
  --orange: #ff7b10;
  --purple: #ed9834;
  --lilac: #ffedda;
  --yellow: #ffe8b0;
}

body {
  color: var(--ink);
  background:
    radial-gradient(
      ellipse at 85% 0%,
      #ffe3c4 0,
      transparent 35%
    ),
    radial-gradient(
      ellipse at 100% 100%,
      #ffe5ca 0,
      transparent 30%
    ),
    #fff8f0;
  font-family: "Segoe UI", Arial, sans-serif;
}

[hidden] {
  display: none !important;
}

.layout {
  max-width: 1530px;
  min-height: 100vh;
  margin: auto;
  padding: 20px;
  display: grid;
  grid-template-columns:
    215px minmax(0,1fr) 295px;
  gap: 22px;
  align-items: start;
}

.sidebar {
  position: sticky;
  top: 20px;
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 40px);
  padding: 24px 14px;
  border: 1px solid #fff;
  border-radius: 27px;
  background: #ffffffee;
  box-shadow: 0 14px 39px #c998671b;
}

.brand {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 6px 41px;
  font-size: 20px;
  letter-spacing: -.9px;
  white-space: nowrap;
}

.brand::before {
  content: "▶";
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  padding-left: 3px;
  flex-shrink: 0;
  border-radius: 11px;
  background: linear-gradient(
    135deg,#ffab35,#ff7612
  );
  color: #fff;
  font-size: 17px;
  box-shadow: 0 6px 14px #fda33d54;
}

.brand span {
  color: #ec9e35;
}

.sidebar nav {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar .nav {
  margin: 0;
  padding: 15px 13px;
  border: 0;
  border-radius: 14px;
  background: transparent;
  color: #625c61;
  font-size: 13px;
  font-weight: 750;
  transition: transform .2s,background .2s;
}

.sidebar .nav:hover {
  background: #fff1df;
  transform: translateX(3px);
}

.sidebar .nav.active {
  background: linear-gradient(
    110deg,#ffab36,#ff7915
  );
  color: white;
  box-shadow: 0 7px 18px #ff963e50;
}

/* The old Downloads button must stay in the DOM
   because original JavaScript references it. */
#navDownloads {
  display: none !important;
}

#downloadsPage {
  display: none !important;
}

/* Hide old tools in the sidebar only. */
.sidebar > .download-box,
.sidebar > .sidebar-note,
.sidebar > .sidebar-heading {
  display: none !important;
}

.ref-sidebar-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: auto;
  padding: 18px 8px 0;
  font-size: 12px;
  font-weight: 750;
}

.ref-avatar {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #262329;
  color: white;
}

main {
  min-width: 0;
}

/* REFERENCE HERO */

.ref-hero {
  position: relative;
  min-height: 260px;
  padding: 25px 7px;
}

.ref-badge {
  display: inline-flex;
  align-items: center;
  padding: 9px 17px;
  border-radius: 30px;
  background: #ffead9;
  color: #894732;
  font-size: 12px;
  font-weight: 800;
}

.ref-hero h1 {
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 1;
  width: max-content;
  max-width: 100%;
  margin: 15px 0 0;
  font-size: clamp(37px,4.2vw,66px);
  font-weight: 950;
  letter-spacing: -2.9px;
  line-height: 1.04;
}

.ref-orange-text {
  position: relative;
  color: #f46d09;
}

.ref-orange-text::after {
  content: "";
  position: absolute;
  right: 2%;
  bottom: -9px;
  width: 69%;
  height: 4px;
  border-radius: 80%;
  background: #efad58;
}

.ref-hero .tagline {
  display: none;
}

/* INTERACTIVE 3D PLAY TILE */

.ref-floating-play {
  --rx: 0deg;
  --ry: 0deg;
  position: absolute;
  right: 4%;
  top: 50px;
  z-index: 2;
  width: 109px;
  height: 109px;
  border: 1px solid white;
  border-radius: 25px;
  cursor: pointer;
  background: linear-gradient(
    135deg,#fff,#fff1e1
  );
  box-shadow:
    5px 7px 0 #ffebd4,
    14px 20px 30px #cb91594a;
  transform:
    perspective(650px)
    rotateX(var(--rx))
    rotateY(var(--ry))
    rotateZ(12deg);
  animation: refFloat 4s ease-in-out infinite;
  transition: transform .16s ease;
}

.ref-floating-play::before {
  content: "";
  position: absolute;
  top: 29%;
  left: 35%;
  border-top: 23px solid transparent;
  border-bottom: 23px solid transparent;
  border-left: 40px solid #ff7b10;
  filter: drop-shadow(3px 4px 3px #d98945);
}

.ref-floating-play:focus-visible {
  outline: 3px solid #ff9b35;
}

@keyframes refFloat {
  0%,100% { translate: 0 0; }
  50% { translate: 0 -9px; }
}

.ref-sparkle {
  position: absolute;
  right: 35%;
  top: 65px;
  color: #eda035;
  font-size: 28px;
  pointer-events: none;
}

/* UPLOAD CARD */

.card {
  border: 1px solid #f7e4d4;
  border-radius: 21px;
  background: #ffffffef;
  box-shadow: 0 12px 32px #c9976219;
}

#inputSection {
  padding: 19px;
}

#inputSection > .step {
  display: none;
}

#inputSection .grid2 {
  position: relative;
  grid-template-columns:
    minmax(0,1fr) minmax(0,1fr);
  gap: 37px;
  align-items: center;
}

#inputSection .grid2::after {
  content: "OR";
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%,-50%);
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: #fff8ef;
  font-size: 11px;
  font-weight: 900;
}

.upload {
  display: flex;
  min-height: 180px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 17px;
  border: 2px dashed #f0d9c4;
  background: #fffcf9;
  border-radius: 15px;
  text-align: center;
  transition:
    transform .2s,
    border-color .2s,
    box-shadow .2s;
}

.upload:hover,
.upload.dragging {
  transform: translateY(-3px);
  border-color: #ff952b;
  background: #fff4e6;
  box-shadow: 0 9px 20px #c48e5627;
}

.upload strong {
  margin: 10px 0 5px;
  font-size: 13px;
}

.upload .muted {
  font-size: 11px;
}

.upload::after {
  content: "📁  Choose File";
  margin-top: 13px;
  padding: 10px 23px;
  border-radius: 25px;
  color: white;
  font-size: 12px;
  font-weight: 850;
  background: linear-gradient(
    105deg,#ffa735,#ff7811
  );
  box-shadow: 0 5px 13px #ff993f51;
}

#videoUrl {
  margin-top: 11px;
  border: 1px solid #e7d9cc;
  background: white;
  border-radius: 12px;
  font-size: 12px;
}

.ref-fetch {
  width: 100%;
  margin-top: 13px;
  padding: 13px;
  border: 0;
  border-radius: 12px;
  color: white;
  font-weight: 850;
  background: linear-gradient(
    105deg,#ffa735,#ff7510
  );
}

.primary,
#processVideo {
  border: 0;
  border-radius: 13px;
  color: white;
  background: linear-gradient(
    105deg,#ffab37,#ff7410
  );
  box-shadow: 0 7px 16px #fe973e4d;
  font-weight: 900;
}

.primary:hover:not(:disabled),
.ref-fetch:hover,
.btn.orange:hover {
  transform: translateY(-2px);
}

#processVideo {
  margin-top: 18px;
  padding: 15px;
}

/* METHOD CARDS */

#choiceSection {
  margin-top: 25px;
  padding: 0;
  border: 0;
  background: transparent;
  box-shadow: none;
}

#choiceSection > .step {
  display: none;
}

.ref-method-heading {
  margin: 0 0 17px;
  font-size: 21px;
  font-weight: 900;
}

#choiceSection .grid2 {
  gap: 16px;
}

.choice {
  display: grid;
  grid-template-columns: 47px 1fr 35px;
  grid-template-rows: auto auto;
  align-items: center;
  column-gap: 10px;
  min-height: 100px;
  padding: 14px;
  border: 1px solid white;
  border-radius: 19px;
  background: white;
  box-shadow: 0 11px 25px #d6a47723;
  transition: transform .23s,box-shadow .23s;
}

.choice:hover:not(:disabled) {
  transform:
    perspective(650px)
    rotateX(4deg)
    translateY(-5px);
  box-shadow: 0 17px 29px #cd93592e;
  background: #fff9f0;
}

.choice .emoji {
  grid-column: 1;
  grid-row: 1 / 3;
  display: grid;
  place-items: center;
  width: 47px;
  height: 47px;
  border-radius: 15px;
  background: #ffefdd;
}

.choice strong {
  grid-column: 2;
  grid-row: 1;
  margin: 0;
  font-size: 12px;
}

.choice small {
  grid-column: 2;
  grid-row: 2;
  font-size: 10px;
}

.choice::after {
  content: "➜";
  grid-column: 3;
  grid-row: 1 / 3;
  display: grid;
  place-items: center;
  width: 35px;
  height: 35px;
  border-radius: 50%;
  color: white;
  background: #ff851b;
  box-shadow: 0 4px 0 #d86b12;
}

/* LIVE PREVIEW */

.preview-column {
  position: sticky;
  top: 59px;
  margin-top: 35px;
  align-self: start;
}

.preview {
  overflow: visible;
  padding: 45px 11px 11px;
  border: 0;
  border-radius: 22px;
  background: white;
  box-shadow: 0 18px 37px #b7926826;
  transition: transform .2s;
}

.preview:hover {
  transform: translateY(-4px);
}

.video-stage {
  position: relative;
  aspect-ratio: 9/16;
  max-height: none;
  overflow: visible;
  border-radius: 12px;
  background: #182132;
}

.video-stage video {
  width: 100%;
  height: 100%;
  border-radius: 12px;
  object-fit: contain;
}

.preview-pill {
  top: -35px;
  left: 0;
  color: #29242a;
  background: transparent;
}

.ratio {
  top: -34px;
  right: 2px;
  padding: 5px 10px;
  border-radius: 25px;
  background: #888692;
}

.empty-preview {
  overflow: hidden;
  border-radius: 12px;
  background:
    radial-gradient(
      circle at 62% 35%,
      #ffe5aa,transparent 18%
    ),
    linear-gradient(
      #c4cfe5,#eeb9ad 58%,#51607d
    );
}

.empty-preview > div {
  display: none;
}

.empty-preview::before {
  content: "";
  position: absolute;
  inset: 46% 0 0;
  background: #495572;
  clip-path: polygon(
    0 40%,25% 20%,44% 50%,
    68% 10%,100% 42%,
    100% 100%,0 100%
  );
}

.empty-preview::after {
  content: "▶";
  position: absolute;
  top: 50%;
  left: 50%;
  width: 68px;
  height: 68px;
  display: grid;
  place-items: center;
  transform: translate(-50%,-50%);
  border-radius: 50%;
  background: #252b41b5;
  color: white;
  font-size: 28px;
}

/* SETTINGS — ACTUAL CONTROLS */

#settingsPage,
#projectsPage {
  margin-top: 24px;
  padding: 25px;
}

#settingsPage h2,
#projectsPage h2 {
  font-size: 29px;
}

.settings-grid {
  display: grid;
  grid-template-columns:
    repeat(2,minmax(0,1fr));
  gap: 17px;
  margin-top: 22px;
}

#settingsPage .download-box,
#settingsPage .sidebar-note,
#settingsPage .settings-channel {
  display: block !important;
  width: 100%;
  min-width: 0;
  margin: 0;
  padding: 21px;
  border: 1px solid #f0dcc9;
  border-radius: 17px;
  background: #fffaf5;
  box-shadow: 0 7px 19px #c4956220;
}

#settingsPage h3 {
  margin: 0 0 15px;
  font-size: 17px;
}

#settingsPage .input {
  background: white;
  border-radius: 11px;
}

#settingsPage .download-link,
#settingsPage #exportMP3 {
  color: white;
  background: linear-gradient(
    100deg,#ffa636,#ff7914
  );
  border: 0;
}

#settingsPage .sidebar-note strong {
  margin-top: 5px;
}

#settingsPage .sidebar-note p {
  background: #fff1e2;
  border-radius: 9px;
  padding: 8px 10px;
}

.settings-channel p {
  overflow-wrap: anywhere;
}

.project-entry {
  padding: 18px;
  border-radius: 15px;
  border: 1px solid #f0ddca;
  background: #fff8ef;
}

/* PUBLISHING GALLERY */

.publish-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 15px;
  margin: 15px 0;
  border: 1px solid #f2d1b3;
  border-radius: 13px;
  background: #fff0e1;
}

.publish-review,
.publish-fields {
  padding: 15px;
  margin-top: 14px;
  border: 1px solid #f1dac5;
  border-radius: 13px;
  background: #fffdf9;
}

.publish-fields label {
  display: block;
  margin-top: 12px;
}

.publish-fields textarea {
  display: block;
  width: 100%;
  min-height: 75px;
}

.publish-checkbox {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 10px 0;
}

.publish-checkbox input {
  accent-color: #ff8625;
}

.publish-status {
  margin-top: 9px;
  font-size: 12px;
  overflow-wrap: anywhere;
}

.publish-success { color: #21814c; }
.publish-error { color: #b83030; }

/* RESPONSIVE */

@media (max-width: 1100px) {
  .layout {
    grid-template-columns:
      190px minmax(0,1fr);
  }

  .preview-column {
    grid-column: 2;
    position: static;
    width: min(100%,360px);
    margin: 0 auto;
  }
}

@media (max-width: 700px) {
  .layout {
    display: flex;
    flex-direction: column;
    padding: 10px;
  }

  .sidebar {
    position: static;
    width: 100%;
    min-height: auto;
  }

  .sidebar nav {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }

  .ref-hero {
    min-height: 225px;
  }

  .ref-hero h1 {
    font-size: clamp(35px,9vw,52px);
  }

  .ref-floating-play {
    width: 65px;
    height: 65px;
    right: 0;
  }

  .ref-floating-play::before {
    border-top-width: 14px;
    border-bottom-width: 14px;
    border-left-width: 24px;
  }

  #inputSection .grid2,
  #choiceSection .grid2,
  .settings-grid {
    grid-template-columns: 1fr;
  }

  .preview-column {
    width: min(100%,350px);
  }

  .video-stage {
    aspect-ratio: 9/16;
    max-height: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ref-floating-play {
    animation: none;
  }

  * {
    scroll-behavior: auto !important;
  }
}
</style>
"""

javascript = r"""
<script>
/* SHORTS AI — CLEAN NAVIGATION & SETTINGS */

(() => {
  "use strict";

  const byId = id => document.getElementById(id);
  const sidebar = document.querySelector(".sidebar");
  const main = document.querySelector("main");
  const nav = sidebar.querySelector("nav");

  // -----------------------------------------
  // Sidebar: Create / Projects / Highlights / Settings
  // -----------------------------------------

  function makeNav(id, label, before = null) {
    let button = byId(id);

    if (!button) {
      button = document.createElement("button");
      button.type = "button";
      button.className = "nav";
      button.id = id;
      button.textContent = label;

      if (before) {
        nav.insertBefore(button, byId(before));
      } else {
        nav.append(button);
      }
    }

    return button;
  }

  const projectsNav = makeNav(
    "navProjects",
    "▱  My Projects",
    "navHighlights"
  );

  const settingsNav = makeNav(
    "navSettings",
    "⚙  Settings"
  );

  // -----------------------------------------
  // Settings page
  // -----------------------------------------

  const settingsPage = document.createElement("section");
  settingsPage.id = "settingsPage";
  settingsPage.className = "card";
  settingsPage.hidden = true;

  const settingsTitle = document.createElement("h2");
  settingsTitle.textContent = "⚙ Settings";

  const settingsGrid = document.createElement("div");
  settingsGrid.className = "settings-grid";

  settingsPage.append(settingsTitle, settingsGrid);
  main.append(settingsPage);

  // IMPORTANT: these are the actual classes in
  // the original uploaded HTML: .download-box
  function moveExistingCard(id, title) {
    const control = byId(id);
    const card = control?.closest(".download-box");

    if (!card) {
      console.error("Missing original card:", id);
      return;
    }

    const heading = card.querySelector("h3");

    if (heading) heading.textContent = title;

    // appendChild MOVES an existing element.
    // Existing event handlers stay attached.
    settingsGrid.appendChild(card);
  }

  moveExistingCard(
    "quality",
    "↓ Export & Download"
  );

  moveExistingCard(
    "exportMP3",
    "♫ Audio Export"
  );

  // Move the actual project and workflow note.
  // Original class: .sidebar-note
  // Original project ID: currentProject
  const projectNote =
    sidebar.querySelector(".sidebar-note");

  if (projectNote) {
    settingsGrid.appendChild(projectNote);
  }

  // Hide obsolete sidebar-only heading labels.
  sidebar.querySelectorAll(".sidebar-heading")
    .forEach(node => node.remove());

  // Old single-upload UI stays hidden.
  // Publishing is handled through My Highlights.
  const auto = byId("autoYoutube");

  if (auto) {
    auto.checked = false;
    auto.disabled = true;
  }

  // Read-only YouTube channel settings card.
  const channelCard = document.createElement("div");
  channelCard.className = "settings-channel";

  const channelTitle = document.createElement("h3");
  channelTitle.textContent = "▶ YouTube Connection";

  const channelInfo = document.createElement("p");
  channelInfo.className = "muted";
  channelInfo.textContent = "Checking connection...";

  const refresh = document.createElement("button");
  refresh.className = "btn orange";
  refresh.type = "button";
  refresh.textContent = "Check Connection";

  channelCard.append(
    channelTitle,
    channelInfo,
    refresh
  );

  settingsGrid.append(channelCard);

  async function checkChannel() {
    try {
      const result = await api("/publish/channel");

      channelInfo.textContent = result.connected
        ? "✓ Connected to " + result.channel_name
        : result.reason || "Not connected";

    } catch (error) {
      channelInfo.textContent = error.message;
    }
  }

  refresh.onclick = checkChannel;

  // -----------------------------------------
  // My Projects: real current project view
  // -----------------------------------------

  const projectsPage = document.createElement("section");
  projectsPage.id = "projectsPage";
  projectsPage.className = "card";
  projectsPage.hidden = true;

  const projectsTitle = document.createElement("h2");
  projectsTitle.textContent = "My Projects";

  const projectEntry = document.createElement("div");
  projectEntry.className = "project-entry";

  const projectText = document.createElement("strong");
  const projectDetail = document.createElement("p");
  projectDetail.className = "muted";

  const openProject = document.createElement("button");
  openProject.className = "btn orange";
  openProject.type = "button";
  openProject.textContent = "Open Current Project →";

  projectEntry.append(
    projectText,
    projectDetail,
    openProject
  );

  projectsPage.append(
    projectsTitle,
    projectEntry
  );

  main.append(projectsPage);

  function refreshProjects() {
    const ready = Boolean(state.filename);

    projectText.textContent = ready
      ? byId("currentProject").textContent
      : "No video selected";

    projectDetail.textContent = ready
      ? "Your current video project is ready."
      : "Upload a video to create a project.";

    openProject.hidden = !ready;
  }

  openProject.onclick = () => showPage("create");

  // -----------------------------------------
  // Reference hero & 3D play tile
  // -----------------------------------------

  const heading = main.querySelector("h1");
  const tagline = main.querySelector(".tagline");

  const hero = document.createElement("header");
  hero.className = "ref-hero";

  heading.before(hero);

  const badge = document.createElement("div");
  badge.className = "ref-badge";
  badge.textContent = "✦  AI Powered";

  heading.replaceChildren();

  const line1 = document.createElement("span");
  line1.textContent = "Big ideas.";

  const line2 = document.createElement("span");
  line2.className = "ref-orange-text";
  line2.textContent = "Short videos.";

  heading.append(line1, line2);

  const tile = document.createElement("button");
  tile.type = "button";
  tile.className = "ref-floating-play";
  tile.setAttribute(
    "aria-label",
    "Choose a video to upload"
  );

  const sparkle = document.createElement("span");
  sparkle.className = "ref-sparkle";
  sparkle.textContent = "✦";

  hero.append(
    badge,heading,tagline,tile,sparkle
  );

  tile.onclick = () => byId("videoFile").click();

  tile.addEventListener("pointermove", event => {
    if (matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches) return;

    const rect = tile.getBoundingClientRect();

    const x =
      (event.clientX - rect.left) / rect.width - .5;

    const y =
      (event.clientY - rect.top) / rect.height - .5;

    tile.style.setProperty(
      "--rx", (-y * 15) + "deg"
    );

    tile.style.setProperty(
      "--ry", (x * 15) + "deg"
    );
  });

  tile.addEventListener("pointerleave", () => {
    tile.style.setProperty("--rx", "0deg");
    tile.style.setProperty("--ry", "0deg");
  });

  // Sidebar footer.
  const footer = document.createElement("div");
  footer.className = "ref-sidebar-footer";

  const avatar = document.createElement("span");
  avatar.className = "ref-avatar";
  avatar.textContent = "AI";

  const footerText = document.createElement("span");
  footerText.textContent = "Creator Studio";

  footer.append(avatar, footerText);
  sidebar.append(footer);

  // -----------------------------------------
  // Upload and method enhancements
  // -----------------------------------------

  const uploadLabel = document.querySelector(".upload");

  const uploadTitle = uploadLabel.querySelector("strong");
  uploadTitle.textContent = "Drag & drop your video here";

  const videoUrl = byId("videoUrl");
  videoUrl.placeholder =
    "https://www.youtube.com/watch?v=...";

  const fetchButton = document.createElement("button");
  fetchButton.id = "fetchVideo";
  fetchButton.type = "button";
  fetchButton.className = "ref-fetch";
  fetchButton.textContent = "Fetch Video →";

  videoUrl.insertAdjacentElement(
    "afterend", fetchButton
  );

  fetchButton.onclick = () => {
    if (!videoUrl.value.trim()) {
      message(
        "processStatus",
        "Enter a video URL.",
        "error"
      );
      return;
    }

    byId("videoFile").value = "";
    byId("fileName").textContent = "";

    byId("processVideo").click();
  };

  // Drag and drop using the real file input.
  uploadLabel.addEventListener("dragover", event => {
    event.preventDefault();
    uploadLabel.classList.add("dragging");
  });

  uploadLabel.addEventListener("dragleave", () => {
    uploadLabel.classList.remove("dragging");
  });

  uploadLabel.addEventListener("drop", event => {
    event.preventDefault();
    uploadLabel.classList.remove("dragging");

    const files = event.dataTransfer?.files;
    if (!files?.length) return;

    if (!files[0].name.toLowerCase().endsWith(".mp4")) {
      message(
        "processStatus",
        "Upload an MP4 file.",
        "error"
      );
      return;
    }

    try {
      byId("videoFile").files = files;

      byId("videoFile").dispatchEvent(
        new Event("change", {bubbles:true})
      );

    } catch {
      message(
        "processStatus",
        "Use Choose File to upload.",
        "error"
      );
    }
  });

  const choice = byId("choiceSection");

  const methodTitle = document.createElement("h2");
  methodTitle.className = "ref-method-heading";
  methodTitle.textContent = "✦  Choose a Method";

  choice.insertBefore(
    methodTitle,
    choice.querySelector(".grid2")
  );

  // Show methods on Create even before upload,
  // but keep buttons disabled until video is ready.
  const oldDrawStage = drawStage;

  drawStage = function() {
    oldDrawStage();

    if (state.page === "create") {
      choice.hidden = false;

      byId("chooseManual").disabled =
        !state.filename;

      byId("chooseAI").disabled =
        !state.filename || state.busy;
    }
  };

  // -----------------------------------------
  // Navigation: no popups and no redirects
  // -----------------------------------------

  const originalShowPage = showPage;

  showPage = function(page) {
    originalShowPage(page);

    settingsPage.hidden = page !== "settings";
    projectsPage.hidden = page !== "projects";
    hero.hidden = page !== "create";

    const activePages = {
      navCreate: "create",
      navProjects: "projects",
      navHighlights: "library",
      navSettings: "settings"
    };

    for (const [id,name] of Object.entries(
      activePages
    )) {
      byId(id).classList.toggle(
        "active", page === name
      );
    }
  };

  projectsNav.onclick = () => {
    refreshProjects();
    showPage("projects");
  };

  settingsNav.onclick = async () => {
    showPage("settings");
    await checkChannel();
  };

  // The original publishing script still handles
  // My Highlights and its review/upload flow.
  // No extra confirmation to switch sections.

  showPage("create");
  drawStage();
})();
</script>
"""

clean_html = (
    base.rstrip()
    + "\n\n"
    + css.strip()
    + "\n\n"
    + publishing_script.strip()
    + "\n\n"
    + javascript.strip()
    + "\n</body>\n</html>\n"
)

# Back up before replacing anything.
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

backup = path.with_name(
    f"index_backup_{stamp}.html"
)

backup.write_text(source, encoding="utf-8")

path.write_text(clean_html, encoding="utf-8")

print("Frontend cleaned successfully.")
print("Updated:", path.resolve())
print("Backup:", backup.resolve())
print(
    "Removed old conflicting UI code:",
    len(source) - len(clean_html),
    "characters (net)"
)
