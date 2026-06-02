import csv
import sys
import os
import base64
from datetime import datetime, timedelta
from pathlib import Path
import requests
from urllib.parse import quote

# ── SAME helper (consistent across all files) ────────────────────────────────
def get_last_week():
    today = datetime.now().date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_friday = last_monday + timedelta(days=4)
    return last_monday, last_friday

def get_week_folder():
    start, end = get_last_week()
    return f"{start}_{end}"

# ── Configuration (ONLY CHANGED HERE) ────────────────────────────────────────
SLIDE_DURATION_MS = 6000
AUTO_REFRESH_MS   = 300000
TOP_N             = 10

# ── Dynamic Paths ────────────────────────────────────────────────────────────
week_folder = get_week_folder()

DEFAULT_CSV  = f"data/processed/{week_folder}/top10.csv"
LATEST_HTML  = "output/latest/leaderboard.html"
HISTORY_HTML = f"output/history/{week_folder}.html"

# ── Helpers (UNCHANGED) ──────────────────────────────────────────────────────
RANK_SUFFIX = {1: "st", 2: "nd", 3: "rd"}

# Required secret: fail fast if missing instead of running with empty auth.
API_KEY = os.environ["HUB_API_KEY"]

def fetch_photo_url(email):
    if not email:
        return ""

    email = quote(email)

    url = f"https://api.hub.york.ie/api/external/interview/get-profile-pic/{email}"

    headers = {
        "x-api-key": API_KEY,
        "Authorization": f"Bearer {API_KEY}",
        "Origin": "https://support.yorkdevs.link/"
    }

    try:
        res = requests.get(url, headers=headers, timeout=10)

        if res.status_code != 200:
            return ""

        data = res.json()

        # ✅ YOUR ACTUAL STRUCTURE
        return data.get("data", {}).get("url", "")

    except Exception as e:
        print(f"⚠️ Error fetching image for {email}: {e}")
        return ""

def rank_suffix(n):
    return RANK_SUFFIX.get(n, "th")

def medal_color(rank):
    return {1: "#22c55e", 2: "#94a3b8", 3: "#cd7f32"}.get(rank, "#64748b")

def photo_to_base64(path):
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    ext = p.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    with open(p, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{data}"

def read_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    rows.sort(key=lambda r: float(r.get("final_score", 0)), reverse=True)

    for i, row in enumerate(rows[:TOP_N], 1):
        row["_rank"] = i

    return rows[:TOP_N]

# ── Card + HTML (UNCHANGED — kept EXACTLY SAME) ──────────────────────────────
def build_card(row):
    rank        = row["_rank"]
    name        = row.get("Name", "—").upper()
    title       = row.get("title", "")
    ai_lines    = f"{int(float(row.get('Total_AI_Lines', 0))):,}"
    usage_score = float(row.get("usage_score", 0))
    total_prompts = row.get("total_prompts", "—")
    quality_score = float(row.get("quality_norm", 0))
    active_days = row.get("Active_Days", "—")
    final_score = float(row.get("final_score", 0))
    email = row.get("Email", "").strip().lower()
    photo_url = f"/faces/{name.lower().replace(" ","-")}_{email.lower()}.png"
    # photo_url = fetch_photo_url(email)

    photo_html = (
        f'<img src="{photo_url}" alt="{name}" class="avatar-img" />'
        if photo_url else
        f'<div class="avatar-placeholder">{name[0]}</div>'
    )

    suffix = rank_suffix(rank)
    color  = medal_color(rank)

    return f"""
<div class="slide" data-rank="{rank}">
  <div class="card">

    <!-- Header bar -->
    <div class="card-header">
      <div class="brand">
    <img src="/output/latest/York-logo-.png" class="brand-logo" />
    <span class="brand-name">Cursor Usage</span>
    </div>
      <div class="badge-weekly">
        <span>Weekly</span>
        <span class="badge-bold">Leaderboard</span>
      </div>
    </div>

    <!-- Person section -->
    <div class="person-section">
      <div class="rank-circle" style="--rank-color:{color}">
        <span class="rank-num">{rank}<sup>{suffix}</sup></span>
        <div class="avatar-ring" style="border-color:{color}">
          {photo_html}
        </div>
      </div>
      <div class="name-block">
        <h1 class="person-name">{name}</h1>
        <p class="person-title">{title}</p>
      </div>
    </div>

    <!-- Stats -->
    <div class="stats-grid">
      <div class="stat-side-label">
        <strong>Usage Score:</strong> Calculated based on consistency of usage and total AI-generated output.
      </div>

      <div class="stat-col">
        <div class="stat-col-header">USAGE</div>
        <div class="stat-item">Total AI Lines: <strong>{ai_lines}</strong></div>
        <div class="stat-item">Usage score: <strong>{usage_score:.1f}</strong></div>
      </div>

      <div class="stat-divider"></div>

      <div class="stat-col">
        <div class="stat-col-header">QUALITY</div>
        <div class="stat-item">Total Prompts: <strong>{total_prompts}</strong></div>
        <div class="stat-item">Quality Score: <strong>{quality_score:.1f}</strong></div>
      </div>

      <div class="stat-side-label right">
        <strong>Quality Score:</strong> Calculated based on overall prompt effectiveness across usage.
      </div>
    </div>

    <div class="active-days">Active Days: <strong>{active_days}</strong></div>

    <div class="final-score-bar">
      Final score: <strong>{final_score:.2f}</strong>
    </div>

    <p class="final-note">Final Score: Combined score based on equal weightage of Usage and Quality.</p>

    <!-- Slide indicator dots (filled by JS) -->
    <div class="dots-row" id="dots"></div>
  </div>
</div>
"""

# ── Full HTML ──────────────────────────────────────────────────────────────────

def build_html(rows):
    cards_html = "\n".join(build_card(r) for r in rows)
    generated  = datetime.now().strftime("%Y-%m-%d %H:%M")
    total      = len(rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AI Leverage – Weekly Leaderboard</title>
<!-- Auto-refresh every {AUTO_REFRESH_MS // 1000} seconds to pick up CSV changes -->
<meta http-equiv="refresh" content="{AUTO_REFRESH_MS // 1000}"/>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap');

  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --green:    #22c55e;
    --green-lt: #dcfce7;
    --dark:     #0f2318;
    --text:     #1a1a1a;
    --muted:    #555;
    --bg:       #f0f7f2;
  }}

  html, body {{
    width: 100%; height: 100%;
    background: var(--dark);
    font-family: 'Plus Jakarta Sans', sans-serif;
    overflow: hidden;
  }}

  /* ── Slideshow ── */
  .slideshow {{
    width: 100vw; height: 100vh;
    position: relative;
  }}

  .brand-logo {{
    width: 35px;
    height: 35px;
    object-fit: contain;
    }}

  .slide {{
    position: absolute; inset: 0;
    display: flex; align-items: center; justify-content: center;
    opacity: 0;
    transform: scale(0.97) translateY(12px);
    transition: opacity 0.7s ease, transform 0.7s ease;
    pointer-events: none;
  }}
  .slide.active {{
    opacity: 1; transform: scale(1) translateY(0);
    pointer-events: all;
  }}
  .slide.exit {{
    opacity: 0; transform: scale(1.03) translateY(-12px);
  }}

  /* ── Card ── */
  .card {{
    background: white;
    border-radius: 24px;
    width: min(920px, 95vw);
    padding: 36px 40px 28px;
    box-shadow: 0 30px 80px rgba(0,0,0,0.5);
    position: relative;
    overflow: hidden;
  }}
  .card::before {{
    content: '';
    position: absolute; top: 0; left: 0; right: 0; height: 5px;
    background: linear-gradient(90deg, var(--green), #4ade80, var(--green));
  }}

  /* ── Header ── */
  .card-header {{
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 28px;
  }}
  .brand {{ display: flex; align-items: center; gap: 10px; }}
  .brand-name {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 2rem; color: var(--text); letter-spacing: 1px;
  }}
  .badge-weekly {{
    background: var(--dark);
    color: white; border-radius: 10px;
    padding: 8px 18px; text-align: center;
    font-weight: 700; font-size: .85rem; line-height: 1.3;
    transform: rotate(-2deg);
  }}
  .badge-bold {{ display: block; font-size: 1.1rem; font-style: italic; }}

  /* ── Person section ── */
  .person-section {{
    display: flex; align-items: center; gap: 0;
    margin-bottom: 32px;
  }}
  .rank-circle {{
    position: relative; flex-shrink: 0;
    width: 200px; height: 160px;
  }}
  .rank-num {{
    position: absolute; top: 0; left: 16px;
    font-family: 'Bebas Neue', sans-serif;
    font-size: 4.5rem; color: var(--rank-color, var(--green));
    line-height: 1;
    z-index: 999;
  }}
  .rank-num sup {{ font-size: 1.8rem; vertical-align: super; z-index: 999; }}
  .avatar-ring {{
    position: absolute; bottom: 0; left: 30px;
    width: 140px; height: 140px;
    border-radius: 50%;
    border: 5px solid var(--green);
    overflow: hidden;
    background: var(--green-lt);
    display: flex; align-items: center; justify-content: center;
  }}
  .avatar-img {{ width: 100%; height: 100%; object-fit: cover; }}
  .avatar-placeholder {{
    font-size: 3.5rem; font-weight: 800; color: var(--green);
  }}

  .name-block {{
    background: #f0faf4;
    border-radius: 14px;
    padding: 20px 28px;
    flex: 1;
  }}
  .person-name {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 3rem; letter-spacing: 1px; color: var(--text);
    line-height: 1;
  }}
  .person-title {{
    font-weight: 700; font-size: 1.05rem; color: var(--muted);
    margin-top: 6px;
  }}

  /* ── Stats ── */
  .stats-grid {{
    display: grid;
    grid-template-columns: 1fr auto 12px auto 1fr;
    align-items: start; gap: 0 20px;
    margin-bottom: 14px;
  }}
  .stat-side-label {{
    font-size: .78rem; color: var(--muted); line-height: 1.5;
  }}
  .stat-side-label.right {{ text-align: right; }}
  .stat-col {{ text-align: center; }}
  .stat-col-header {{
    font-weight: 800; font-size: .85rem; color: var(--green);
    letter-spacing: 1px; margin-bottom: 10px;
  }}
  .stat-item {{ font-size: .95rem; color: var(--text); margin-bottom: 6px; }}
  .stat-item strong {{ font-weight: 800; }}
  .stat-divider {{
    width: 2px; background: repeating-linear-gradient(
      to bottom, var(--green) 0 6px, transparent 6px 12px
    );
    align-self: stretch; min-height: 60px;
  }}

  .active-days {{
    text-align: center; font-size: .95rem;
    color: var(--muted); margin-bottom: 16px;
  }}
  .active-days strong {{ color: var(--text); font-weight: 800; }}

  /* ── Final score bar ── */
  .final-score-bar {{
    background: #d1fae5;
    border-radius: 12px;
    padding: 14px;
    text-align: center;
    font-size: 1.4rem; font-weight: 700; color: var(--green);
    margin-bottom: 10px;
  }}
  .final-score-bar strong {{ font-size: 1.6rem; }}
  .final-note {{
    text-align: center; font-size: .78rem; color: var(--muted);
    margin-bottom: 16px;
  }}

  /* ── Dots ── */
  .dots-row {{
    display: flex; justify-content: center; gap: 8px; margin-top: 4px;
  }}
  .dot {{
    width: 10px; height: 10px; border-radius: 50%;
    background: #d1d5db; transition: background .3s, transform .3s;
    cursor: pointer;
  }}
  .dot.active {{ background: var(--green); transform: scale(1.3); }}

  /* ── Generated timestamp ── */
  .timestamp {{
    position: fixed; bottom: 14px; right: 20px;
    font-size: .72rem; color: rgba(255,255,255,.35);
    font-family: monospace;
  }}

  /* ── Progress bar ── */
  .progress-bar {{
    position: fixed; bottom: 0; left: 0;
    height: 3px; background: var(--green);
    width: 0%; transition: width linear;
    z-index: 99;
  }}
</style>
</head>
<body>

<div class="slideshow" id="slideshow">
  {cards_html}
</div>

<div class="progress-bar" id="progressBar"></div>
<div class="timestamp">Generated: {generated} · Auto-refreshes every {AUTO_REFRESH_MS // 60000} min</div>

<script>
(function() {{
  const DURATION = {SLIDE_DURATION_MS};
  const slides   = Array.from(document.querySelectorAll('.slide'));
  const total    = slides.length;
  let current    = 0;
  let timer      = null;
  let progTimer  = null;

  // Build dots inside every card
  slides.forEach((slide, idx) => {{
    const dotsEl = slide.querySelector('#dots');
    if (!dotsEl) return;
    dotsEl.id = ''; // remove duplicate id
    slides.forEach((_, di) => {{
      const d = document.createElement('span');
      d.className = 'dot' + (di === idx ? ' active' : '');
      d.addEventListener('click', () => goTo(di));
      dotsEl.appendChild(d);
    }});
  }});

  function updateDots(idx) {{
    slides.forEach(slide => {{
      const dots = slide.querySelectorAll('.dot');
      dots.forEach((d, di) => d.classList.toggle('active', di === idx));
    }});
  }}

  function goTo(idx) {{
    slides[current].classList.remove('active');
    slides[current].classList.add('exit');
    setTimeout(() => slides[current].classList.remove('exit'), 700);
    current = (idx + total) % total;
    slides[current].classList.add('active');
    updateDots(current);
    startProgress();
  }}

  function next() {{ goTo(current + 1); }}

  function startProgress() {{
    const bar = document.getElementById('progressBar');
    bar.style.transition = 'none';
    bar.style.width = '0%';
    clearTimeout(progTimer);
    clearTimeout(timer);
    // Small delay to allow reflow
    requestAnimationFrame(() => requestAnimationFrame(() => {{
      bar.style.transition = `width ${{DURATION}}ms linear`;
      bar.style.width = '100%';
    }}));
    timer = setTimeout(next, DURATION);
  }}

  // Keyboard nav
  document.addEventListener('keydown', e => {{
    if (e.key === 'ArrowRight' || e.key === ' ') next();
    if (e.key === 'ArrowLeft') goTo(current - 1);
  }});

  // Start
  slides[0].classList.add('active');
  updateDots(0);
  startProgress();
}})();
</script>
<script>
(function () {{
  var HOLD_MS = 10000;
  var EXIT_MS = 700;
  var QUEUE_CAP = 10;
  var RECONNECT_INITIAL_MS = 1000;
  var RECONNECT_MAX_MS = 30000;
  var LIVE_RANK_COLOR = '#64748b';
  var DEBUG_LIVE = false;
  try {{
    DEBUG_LIVE = new URLSearchParams(window.location.search).has('live_debug');
  }} catch (_) {{}}

  function liveLog() {{
    if (!DEBUG_LIVE) return;
    var args = ['[live]'].concat(Array.prototype.slice.call(arguments));
    console.log.apply(console, args);
  }}

  function resolveWsUrl() {{
    try {{
      var q = new URLSearchParams(window.location.search).get('ws');
      if (q) return q;
    }} catch (_) {{ /* URLSearchParams missing on ancient TVs; fall through */ }}
    if (window.LEADERBOARD_WS_URL) return window.LEADERBOARD_WS_URL;
    return 'wss://cursor-leaderboard.yorkdevs.link/ws';
  }}

  var activeIds = new Set();
  var queue = [];
  var currentLive = null;
  var ws = null;
  var wsUrl = '';
  var backoff = RECONNECT_INITIAL_MS;
  var reconnectTimer = null;
  var slideshow = null;
  var slidePrototype = null;

  function getSlidePrototype() {{
    if (!slideshow) {{
      slideshow = document.getElementById('slideshow');
    }}
    if (!slidePrototype && slideshow) {{
      slidePrototype = slideshow.querySelector('.slide[data-rank]');
      if (!slidePrototype && DEBUG_LIVE) {{
        console.warn('[live] no .slide[data-rank] prototype found in #slideshow');
      }}
    }}
    return slidePrototype;
  }}

  function personId(person) {{
    if (person.id) return String(person.id);
    if (person.email) return String(person.email);
    if (person.face_id) return 'unknown:' + person.face_id;
    return '';
  }}

  function isQueued(id) {{
    for (var i = 0; i < queue.length; i++) {{
      if (queue[i].id === id) return true;
    }}
    return false;
  }}

  function resolveAvatarUrl(person) {{
    if (person.detected_image) return person.detected_image;
    if (!person.image) return '';
    if (String(person.image).indexOf('data:') === 0) return person.image;
    return faceImageUrl(person.image);
  }}

  function faceImageUrl(imageFilename) {{
    if (!imageFilename || !wsUrl) return '';
    if (String(imageFilename).indexOf('data:') === 0) return imageFilename;
    try {{
      var u = new URL(wsUrl);
      u.protocol = u.protocol === 'wss:' ? 'https:' : 'http:';
      u.pathname = '/faces/' + encodeURIComponent(imageFilename);
      u.search = '';
      u.hash = '';
      return u.href;
    }} catch (_) {{
      return '';
    }}
  }}

  function formatMetric(value) {{
    if (value == null || value === '-') return '-';
    if (typeof value === 'number' && !isNaN(value)) {{
      if (Number.isInteger(value)) return value.toLocaleString();
      return value.toFixed(2);
    }}
    return String(value);
  }}

  function setColMetric(statCol, itemIndex, value) {{
    if (!statCol) return;
    var strongs = statCol.querySelectorAll('.stat-item strong');
    if (strongs[itemIndex]) strongs[itemIndex].textContent = formatMetric(value);
  }}

  function showAvatarPlaceholder(ring, person) {{
    var img = ring.querySelector('.avatar-img');
    var letter = ((person.name || person.email || '?').charAt(0) || '?').toUpperCase();
    var ph = document.createElement('div');
    ph.className = 'avatar-placeholder';
    ph.textContent = letter;
    if (img) {{
      img.replaceWith(ph);
    }} else {{
      ring.appendChild(ph);
    }}
  }}

  function showFallbackMetrics(slide, message) {{
    var sideLabels = slide.querySelectorAll('.stat-side-label');
    for (var i = 0; i < sideLabels.length; i++) {{
      sideLabels[i].textContent = '';
    }}
    var cols = slide.querySelectorAll('.stat-col');
    for (var c = 0; c < cols.length; c++) {{
      var strongs = cols[c].querySelectorAll('.stat-item strong');
      for (var s = 0; s < strongs.length; s++) {{
        strongs[s].textContent = '';
      }}
    }}
    var activeDays = slide.querySelector('.active-days');
    if (activeDays) activeDays.textContent = '\u00a0';
    var finalBar = slide.querySelector('.final-score-bar');
    if (finalBar) finalBar.textContent = message;
    var finalNote = slide.querySelector('.final-note');
    if (finalNote) finalNote.style.display = 'none';
  }}

  function fillLiveMetrics(slide, m) {{
    var cols = slide.querySelectorAll('.stat-col');
    setColMetric(cols[0], 0, m.totalAiLines);
    setColMetric(cols[0], 1, m.usageScore != null ? m.usageScore : '-');
    setColMetric(cols[1], 0, m.promptCount);
    setColMetric(cols[1], 1, m.avgScore);

    var activeStrong = slide.querySelector('.active-days strong');
    if (activeStrong) activeStrong.textContent = formatMetric(m.activeDays);

    var finalBar = slide.querySelector('.final-score-bar');
    if (finalBar) {{
      finalBar.innerHTML = 'Final score: <strong>' + formatMetric(
        m.finalScore != null ? m.finalScore : '-'
      ) + '</strong>';
    }}
    var finalNote = slide.querySelector('.final-note');
    if (finalNote) finalNote.style.display = '';
  }}

  function ordinalParts(num) {{
    if (num % 100 >= 11 && num % 100 <= 13) {{
      return {{ number: num, suffix: 'th' }};
    }}

    switch (num % 10) {{  
      case 1: return {{ number: num, suffix: 'st' }};
      case 2: return {{ number: num, suffix: 'nd' }};
      case 3: return {{ number: num, suffix: 'rd' }};
      default: return {{ number: num, suffix: 'th' }};
    }}
  }}

  function fillLiveSlide(slide, person) {{
    console.log(person);
    var employeeFound = person.employee_found !== false;
    var dataFound = person.data_found !== false;
    if (person.employee_found === undefined && person.data_found === undefined) {{
      employeeFound = true;
      dataFound = !!(person.metrics && person.metrics.rank != null);
    }}

    var rankCircle = slide.querySelector('.rank-circle');
    if (rankCircle) rankCircle.style.setProperty('--rank-color', LIVE_RANK_COLOR);

    var rankNum = slide.querySelector('.rank-num');
    if (rankNum) {{ 
      if (employeeFound && dataFound && person.metrics && person.metrics.rank != null) {{
        var parts = ordinalParts(person.metrics.rank);
        rankNum.innerHTML = parts.number + '<sup>' + parts.suffix + '</sup>';
      }} else {{
        rankNum.textContent = '\u2014';
      }}
    }}

    var ring = slide.querySelector('.avatar-ring');
    if (ring) ring.style.borderColor = LIVE_RANK_COLOR;

    var img = slide.querySelector('.avatar-img');
    var avatarUrl = resolveAvatarUrl(person);
    if (img && avatarUrl) {{
      img.src = avatarUrl;
      img.alt = employeeFound ? (person.name || '') : 'Unknown person';
      img.onerror = function () {{ showAvatarPlaceholder(ring, person); }};
    }} else if (ring) {{
      showAvatarPlaceholder(ring, person);
    }}

    var nameEl = slide.querySelector('.person-name');
    if (nameEl) {{
      if (!employeeFound) {{
        nameEl.textContent = 'USER NOT FOUND';
      }} else {{
        nameEl.textContent = (person.name || '').toUpperCase();
      }}
    }}

    var titleEl = slide.querySelector('.person-title');
    if (titleEl) {{
      titleEl.textContent = employeeFound ? (person.email || '') : '';
    }}

    if (employeeFound && dataFound) {{  
      console.log("filling metrics", person.metrics);
      fillLiveMetrics(slide, person.metrics || {{}});
    }} else if (!employeeFound) {{
      console.log("filling fallback metrics", 'User not found');
      showFallbackMetrics(slide, 'User not found');
    }} else {{
      console.log("filling fallback metrics", 'Data not found');
      showFallbackMetrics(slide, 'Data not found');
    }}
  }}

  function buildLiveSlide(person) {{
    var proto = getSlidePrototype();
    if (!proto) {{ return null; }};
    var slide = proto.cloneNode(true);
    slide.classList.remove('active', 'exit');
    slide.removeAttribute('data-rank');
    slide.setAttribute('data-live-id', person.id);
    var dots = slide.querySelector('.dots-row');
    if (dots) {{
      dots.innerHTML = '';
      dots.removeAttribute('id');
    }}
    fillLiveSlide(slide, person);
    return slide;
  }}

  function showNext() {{
    if (currentLive || queue.length === 0) {{ return; }};
    if (!slideshow) {{
      slideshow = document.getElementById('slideshow');
      if (!slideshow) return;
    }}
    while (queue.length > 0) {{
      var person = queue.shift();
      var el = buildLiveSlide(person);
      if (!el) {{
        console.warn('[live] buildLiveSlide failed for', person.id);
        liveLog('build failed, trying next in queue');
        continue;
      }}
      slideshow.appendChild(el);
      void el.offsetWidth;
      el.classList.add('active');
      activeIds.add(person.id);
      liveLog('slide shown', person.id, el);
      var hideTimer = setTimeout(function () {{
        el.classList.remove('active');
        el.classList.add('exit');
      }}, HOLD_MS);
      var removeTimer = setTimeout(function () {{
        if (el.parentNode) el.parentNode.removeChild(el);
        activeIds.delete(person.id);
        currentLive = null;
        liveLog('slide removed', person.id);
        showNext();
      }}, HOLD_MS + EXIT_MS);
      currentLive = {{ id: person.id, el: el, hideTimer: hideTimer, removeTimer: removeTimer }};
      return;
    }}
  }}

  function onMessage(raw) {{
    var msg;
    try {{ msg = JSON.parse(raw); }} catch (_) {{ return; }};
    if (!msg || msg.type !== 'PERSON_DETECTED') return;
    var p = msg.payload;
    if (!p) return;

    var person = {{
      id: '',
      email: p.email != null ? String(p.email) : '',
      name: p.name != null ? String(p.name) : '',
      image: p.image != null ? String(p.image) : '',
      detected_image: p.detected_image != null ? String(p.detected_image) : '',
      face_id: p.face_id != null ? String(p.face_id) : '',
      employee_found: p.employee_found,
      data_found: p.data_found,
      metrics: p.metrics && typeof p.metrics === 'object' ? p.metrics : {{}}
    }};
    person.id = personId(person);
    if (!person.id) {{ return; }};

    liveLog('PERSON_DETECTED', person.id);
    if (activeIds.has(person.id)) return;
    if (isQueued(person.id)) return;
    if (queue.length >= QUEUE_CAP) return;
    queue.push(person);
    showNext();
  }}

  function scheduleReconnect() {{
    if (reconnectTimer) return;
    var delay = backoff;
    reconnectTimer = setTimeout(function () {{
      reconnectTimer = null;
      backoff = Math.min(backoff * 2, RECONNECT_MAX_MS);
      connect();
    }}, delay);
  }}

  function connect() {{
    var url = resolveWsUrl();
    wsUrl = url;
    try {{
      ws = new WebSocket(url);
    }} catch (_) {{
      scheduleReconnect();
      return;
    }}
    ws.onopen = function () {{
      backoff = RECONNECT_INITIAL_MS;
    }};
    ws.onmessage = function (ev) {{ onMessage(ev.data); }};
    ws.onclose = function () {{ scheduleReconnect(); }};
    ws.onerror = function () {{
      try {{ ws.close(); }} catch (_) {{}}
    }};
  }}

  function boot() {{
    slideshow = document.getElementById('slideshow');
    getSlidePrototype();
    connect();
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', boot, {{ once: true }});
  }} else {{
    boot();
  }}
}})();

</script>
</body>
</html>
"""

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    csv_path = DEFAULT_CSV

    if not os.path.exists(csv_path):
        raise Exception(f"❌ Missing input file: {csv_path}")

    rows = read_csv(csv_path)
    html = build_html(rows)

    # ✅ Ensure folders exist
    Path("output/latest").mkdir(parents=True, exist_ok=True)
    Path("output/history").mkdir(parents=True, exist_ok=True)

    # ✅ Save latest (for TV)
    with open(LATEST_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    # ✅ Save history (weekly snapshot)
    with open(HISTORY_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Latest leaderboard → {LATEST_HTML}")
    print(f"✅ History saved → {HISTORY_HTML}")

if __name__ == "__main__":
    main()
