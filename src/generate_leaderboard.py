import csv
import sys
import os
import base64
from datetime import datetime, timedelta
from pathlib import Path

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
    photo_path  = row.get("photo_path", "")
    photo_b64   = photo_to_base64(photo_path)

    photo_html = (
        f'<img src="{photo_b64}" alt="{name}" class="avatar-img" />'
        if photo_b64 else
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
        <svg width="36" height="36" viewBox="0 0 36 36" fill="none">
          <rect width="36" height="36" rx="6" fill="#1a3a2a"/>
          <path d="M8 18 L18 8 L28 18 L18 28 Z" stroke="#22c55e" stroke-width="2" fill="none"/>
          <path d="M12 18 L18 12 L24 18 L18 24 Z" fill="#22c55e" opacity="0.6"/>
        </svg>
        <span class="brand-name">AI Leverage</span>
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
  }}
  .rank-num sup {{ font-size: 1.8rem; vertical-align: super; }}
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
