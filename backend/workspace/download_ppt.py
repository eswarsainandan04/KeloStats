import io
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from playwright.sync_api import sync_playwright


def find_browser_executable() -> Optional[str]:
    """Finds installed Chrome or Edge executable on Windows/Linux."""
    # Standard candidate paths
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path_str in candidates:
        if Path(path_str).exists():
            return path_str

    # Check system PATH
    for name in ["chrome", "google-chrome", "chromium", "msedge"]:
        found = shutil.which(name)
        if found:
            return found

    return None


def parse_css_color(color_str: Optional[str]) -> RGBColor:
    """Parses rgb(r, g, b) or #hex into PPTX RGBColor."""
    if not color_str or not isinstance(color_str, str):
        return RGBColor(0, 0, 0)

    color_clean = color_str.strip().lower()
    rgb_match = re.search(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", color_clean)
    if rgb_match:
        try:
            return RGBColor(int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3)))
        except ValueError:
            pass

    if color_clean.startswith("#"):
        h = color_clean.lstrip("#")
        if len(h) == 3:
            h = "".join([c * 2 for c in h])
        if len(h) >= 6:
            try:
                return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            except ValueError:
                pass

    return RGBColor(0, 0, 0)


def resolve_font_name(font_family: Optional[str]) -> str:
    """Resolves font family to universal PowerPoint desktop fonts (Arial, Georgia)."""
    if not font_family:
        return "Arial"
    f_lower = str(font_family).lower()
    if any(k in f_lower for k in ["georgia", "times", "serif"]):
        return "Georgia"
    return "Arial"


def compile_single_html_slide(page, slide):
    """
    Renders an HTML slide in Playwright:
    1. Extracts all text elements with their exact canvas coordinates, font sizes, weights, and colors.
    2. Temporarily hides text elements and captures a high-resolution PNG screenshot of the background graphics.
    3. Adds the background picture to the PPTX slide.
    4. Overlays native, fully-editable PowerPoint text boxes at exact positions.
    """
    # 1. Measure slide canvas bounding rectangle
    canvas_info = page.evaluate("""() => {
        const c = document.querySelector('.slide-canvas') || document.body;
        const rect = c.getBoundingClientRect();
        return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
    }""")

    # 2. Extract editable text elements relative to the slide canvas
    text_items = page.evaluate("""() => {
        const c = document.querySelector('.slide-canvas') || document.body;
        const cRect = c.getBoundingClientRect();
        const items = [];
        const selector = '[data-editable], h1, h2, h3, h4, h5, h6, p, .author-name, .subtitle-text, .company-name, .topic-number, .topic-text, .metric-value, .metric-label';
        
        document.querySelectorAll(selector).forEach(el => {
            const rect = el.getBoundingClientRect();
            const style = window.getComputedStyle(el);
            const text = el.innerText.trim();
            if (text && rect.width > 0 && rect.height > 0) {
                items.push({
                    text: text,
                    left: rect.left - cRect.left,
                    top: rect.top - cRect.top,
                    width: rect.width,
                    height: rect.height,
                    fontSize: parseFloat(style.fontSize) || 16,
                    color: style.color,
                    fontWeight: style.fontWeight,
                    fontFamily: style.fontFamily,
                    textAlign: style.textAlign
                });
            }
        });
        return items;
    }""")

    # 3. Temporarily hide text so the background screenshot only contains visuals, shapes, cards, charts, and SVGs
    page.evaluate("""() => {
        const selector = '[data-editable], h1, h2, h3, h4, h5, h6, p, .author-name, .subtitle-text, .company-name, .topic-number, .topic-text, .metric-value, .metric-label';
        document.querySelectorAll(selector).forEach(el => {
            el.style.visibility = 'hidden';
        });
    }""")

    # 4. Take high-res screenshot of the canvas element
    locator = page.locator(".slide-canvas")
    if locator.count() > 0:
        bg_bytes = locator.first.screenshot(type="png")
    else:
        bg_bytes = page.screenshot(type="png")

    # 5. Insert background image to PPTX slide (standard 13.333" x 7.5" 16:9 widescreen)
    slide.shapes.add_picture(io.BytesIO(bg_bytes), Inches(0), Inches(0), Inches(13.333), Inches(7.5))

    # 6. Insert native editable text boxes over the background
    canvas_w = canvas_info["width"] or 1920.0
    canvas_h = canvas_info["height"] or 1080.0

    for item in text_items:
        left_in = Inches((item["left"] / canvas_w) * 13.333)
        top_in = Inches((item["top"] / canvas_h) * 7.5)
        width_in = Inches((item["width"] / canvas_w) * 13.333 + 0.15)  # slight breathing room for fonts
        height_in = Inches((item["height"] / canvas_h) * 7.5)

        tx_box = slide.shapes.add_textbox(left_in, top_in, width_in, height_in)
        tf = tx_box.text_frame
        tf.word_wrap = True
        tf.margin_left = Inches(0)
        tf.margin_right = Inches(0)
        tf.margin_top = Inches(0)
        tf.margin_bottom = Inches(0)

        p = tf.paragraphs[0]
        align_str = str(item.get("textAlign", "left")).lower()
        if align_str == "center":
            p.alignment = PP_ALIGN.CENTER
        elif align_str == "right":
            p.alignment = PP_ALIGN.RIGHT
        else:
            p.alignment = PP_ALIGN.LEFT

        run = p.add_run()
        run.text = item["text"]
        run.font.name = resolve_font_name(item.get("fontFamily"))

        # Convert pixel font size to PPTX Pt: 1080px canvas corresponds to 7.5" (540pt) height
        font_pt = (item["fontSize"] / canvas_h) * 540.0
        run.font.size = Pt(max(round(font_pt, 1), 7.0))
        run.font.bold = str(item.get("fontWeight", "")).lower() in ["600", "700", "800", "900", "bold"]
        run.font.color.rgb = parse_css_color(item.get("color"))


def compile_html_slides_to_pptx(slides: List[Dict[str, Any]]) -> bytes:
    """
    Compiles a list of HTML slides into an editable PowerPoint presentation (.pptx).
    - Backgrounds, shapes, SVG dot clusters, charts, tables, and colors are saved as high-res images.
    - All titles, subtitles, metrics, and bullets remain 100% native, clickable, editable text in PowerPoint.
    """
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    browser_exe = find_browser_executable()
    launch_kwargs = {"headless": True}
    if browser_exe:
        launch_kwargs["executable_path"] = browser_exe

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        for s_data in slides:
            html_content = s_data.get("raw_html") or s_data.get("rendered_html") or s_data.get("html") or ""
            if not html_content.strip():
                continue

            page.set_content(html_content)
            page.wait_for_timeout(350)  # Allow fonts and SVG patterns to paint

            ppt_slide = prs.slides.add_slide(blank_layout)
            compile_single_html_slide(page, ppt_slide)

        browser.close()

    out_buf = io.BytesIO()
    prs.save(out_buf)
    out_buf.seek(0)
    return out_buf.getvalue()
