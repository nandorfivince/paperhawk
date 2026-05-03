# PaperHawk — Slide Deck

The 10-slide deck for the AMD Developer Hackathon × lablab.ai submission.

- **Source**: `slides.html` (single self-contained HTML, ~1100 lines, no JS, no external assets except the repo's `paperhawk.jpeg`)
- **Format**: 16:9 landscape (1280 × 720 px per slide)
- **Palette**: AMD red `#ED1C24` + AMD orange `#FB6624` + PaperHawk black `#1A1A1A` + Qwen purple `#7C3AED` accent
- **Typography**: Inter (Google Fonts), JetBrains Mono for code/labels
- **License**: MIT (same as the repo)

## Render to PDF (Playwright)

```bash
# One-time setup
pip install playwright
playwright install chromium

# Render slides.html → PaperHawk_Slides.pdf
python - <<'PY'
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    src = Path("docs/slides/slides.html").resolve().as_uri()
    out = Path("docs/slides/PaperHawk_Slides.pdf")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(src, wait_until="networkidle")
        await page.pdf(
            path=str(out),
            width="1280px",
            height="720px",
            print_background=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        await browser.close()

asyncio.run(main())
print("Wrote", "docs/slides/PaperHawk_Slides.pdf")
PY
```

## Render the cover slide as PNG (HF Space hero)

```bash
python - <<'PY'
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    src = Path("docs/slides/slides.html").resolve().as_uri()
    out = Path("docs/slides/01_cover.png")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(src, wait_until="networkidle")
        # Screenshot the first .slide element only.
        cover = page.locator(".slide").first
        await cover.screenshot(path=str(out), omit_background=False)
        await browser.close()

asyncio.run(main())
print("Wrote", "docs/slides/01_cover.png")
PY
```

## Preview locally

```bash
# Open in your browser (renders identical to the PDF):
xdg-open docs/slides/slides.html
```

## Iteration workflow

1. Edit `slides.html` (CSS at the top, slides as `<section class="slide">` blocks)
2. Reload the browser tab to preview
3. When happy, re-run the Playwright PDF script
4. Commit both `slides.html` and the generated PDF

## Slide map

| # | Title | Visual |
|---|---|---|
| 1 | Cover | `paperhawk.jpeg` hero + team + tagline |
| 2 | The Problem | RAG-vs-audit split contrast |
| 3 | What We Built | 5 big-number stat cards |
| 4 | The Pipeline | 5-step ribbon (red→orange gradient) |
| 5 | The 14 Domain Checks | 3-tier table (audit / compliance / standards) |
| 6 | Anti-Halluc + DD | 5+1 layer stack | DD supervisor pattern |
| 7 | The Stack | Vertical stack-row layout (AMD + Qwen highlighted) |
| 8 | Demo Packages | 3 demo cards + timing banner |
| 9 | Built for Builders | 3 builders cards + repo/HF/MIT meta |
| 10 | Team + Closing | 3 team cards + closing tagline |

## Notes

- All copy is English, builder-energy tone, no PwC/Hungarian narrative residue
- The `paperhawk.jpeg` reference is `../../paperhawk.jpeg` (relative to `docs/slides/`)
- The gradient strip on every slide top is `linear-gradient(90deg, AMD-red → AMD-orange → Qwen-purple)` — a visual signature
- "Team CsimpiCsirkek" appears in the cover meta + final footer; "Built to ship" closing tagline carries the winner-team subtext without being on-the-nose
