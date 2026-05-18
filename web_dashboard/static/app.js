const bboxStatus = document.getElementById("bboxStatus");
const videoStatus = document.getElementById("videoStatus");
const targetClass = document.getElementById("targetClass");
const detectionCount = document.getElementById("detectionCount");
const messageAge = document.getElementById("messageAge");
const source = document.getElementById("source");
const detections = document.getElementById("detections");
const rawJson = document.getElementById("rawJson");
const video = document.getElementById("video");
const mjpegVideo = document.getElementById("mjpegVideo");

let latestMessage = null;
let hlsPlayer = null;
let videoStarted = false;

function setStatus(element, label, ok) {
  element.textContent = label;
  element.classList.toggle("status-ok", ok);
  element.classList.toggle("status-waiting", !ok);
}

function renderBbox(payload) {
  latestMessage = payload;
  const items = payload.detections || [];

  setStatus(bboxStatus, "live", true);
  targetClass.textContent = payload.target_class || "-";
  detectionCount.textContent = String(items.length);
  source.textContent = payload.source || "-";
  rawJson.textContent = JSON.stringify(payload, null, 2);

  detections.replaceChildren(
    ...items.map((item, index) => {
      const card = document.createElement("article");
      card.className = "detection";
      const bbox = item.bbox || {};
      const center = item.center || {};
      card.innerHTML = `
        <div class="detection-title">
          <strong>${index + 1}. ${item.label || "-"}</strong>
          <span>${Number(item.conf || 0).toFixed(2)}</span>
        </div>
        <div class="detection-grid">
          <span>x</span><b>${bbox.x ?? "-"}</b>
          <span>y</span><b>${bbox.y ?? "-"}</b>
          <span>w</span><b>${bbox.w ?? "-"}</b>
          <span>h</span><b>${bbox.h ?? "-"}</b>
          <span>cx</span><b>${center.x ?? "-"}</b>
          <span>cy</span><b>${center.y ?? "-"}</b>
        </div>
      `;
      return card;
    })
  );

  if (items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No detections";
    detections.replaceChildren(empty);
  }
}

function connectEvents() {
  const events = new EventSource("/events");
  events.addEventListener("bbox", (event) => {
    renderBbox(JSON.parse(event.data));
  });
  events.onerror = () => {
    setStatus(bboxStatus, "reconnecting", false);
  };
}

function startVideo() {
  startMjpeg();
}

function startMjpeg() {
  const url = "/mjpeg";
  video.style.display = "none";
  mjpegVideo.style.display = "block";
  setStatus(videoStatus, "mjpeg live", true);
  mjpegVideo.onload = () => {
    videoStarted = true;
    setStatus(videoStatus, "mjpeg live", true);
  };
  mjpegVideo.onerror = () => {
    videoStarted = false;
    setStatus(videoStatus, "mjpeg waiting", false);
  };
  mjpegVideo.src = `${url}?t=${Date.now()}`;
}

function startHlsVideo() {
  const sourceUrl = "/hls/stream.m3u8";
  if (videoStarted) {
    return;
  }

  if (window.Hls && Hls.isSupported()) {
    hlsPlayer = new Hls({
      liveSyncDurationCount: 1,
      maxLiveSyncPlaybackRate: 2,
      lowLatencyMode: true,
    });
    hlsPlayer.loadSource(sourceUrl);
    hlsPlayer.attachMedia(video);
    hlsPlayer.on(Hls.Events.MANIFEST_PARSED, () => {
      videoStarted = true;
      setStatus(videoStatus, "video live", true);
      video.play().catch(() => {});
    });
    hlsPlayer.on(Hls.Events.ERROR, (_event, data) => {
      if (data && data.fatal) {
        hlsPlayer.destroy();
        hlsPlayer = null;
        videoStarted = false;
      }
      setStatus(videoStatus, "video waiting", false);
    });
    return;
  }

  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = sourceUrl;
    video.addEventListener("loadedmetadata", () => {
      videoStarted = true;
      setStatus(videoStatus, "video live", true);
      video.play().catch(() => {});
    });
    return;
  }

  setStatus(videoStatus, "hls.js missing", false);
}

async function pollVideoStatus() {
  if (mjpegVideo.style.display === "block") {
    return;
  }

  try {
    const response = await fetch("/api/video-status", { cache: "no-store" });
    const status = await response.json();
    if (!status.ffmpeg_running) {
      setStatus(videoStatus, "ffmpeg stopped", false);
      return;
    }
    if (!status.playlist_exists || status.segment_count === 0) {
      setStatus(videoStatus, "no hls yet", false);
      return;
    }
    if (!videoStarted && !hlsPlayer) {
      setStatus(videoStatus, "loading video", false);
      startHlsVideo();
    }
  } catch (_error) {
    setStatus(videoStatus, "video status error", false);
  }
}

setInterval(() => {
  if (!latestMessage || !latestMessage.received_at) {
    messageAge.textContent = "-";
    return;
  }
  const age = Math.max(0, Date.now() / 1000 - latestMessage.received_at);
  messageAge.textContent = `${age.toFixed(1)}s`;
  if (age > 2) {
    setStatus(bboxStatus, "stale", false);
  }
}, 250);

connectEvents();
startVideo();
