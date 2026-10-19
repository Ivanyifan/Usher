"""Records the guarded run on the challenge page: an agent fills the form while the page springs all ten traps.

A real run stops at the first blocked submission. For the recording it keeps going and shows, after each step,
which guard stopped what, and says so on screen. The captions come from this script, not from the guards. Writes demo.webm (and demo.mp4 and demo.gif
when ffmpeg is installed) to the output folder.

    python -m challenge.run_demo [output folder]
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

from challenge.server import ChallengeServer
from submit_guard import ClickGuard, ForbiddenClick, ForbiddenKey, GuardStack, KeyGuard, SubmitBlocked
from submit_guard.browser import VIEWPORT, browser_executable

KEYS, CLICKS = KeyGuard(), ClickGuard()
NAMES = {"page_submit": "page guard", "page_enter": "page guard", "form_submit_call": "page guard",
         "network": "network guard", "navigation": "navigation watch"}
_CAPTION_JS = """(text) => {
  let bar = document.getElementById('__demo_caption');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = '__demo_caption';
    bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;padding:14px 24px;background:#1d2330;color:#fff;'
      + 'font:600 18px system-ui,sans-serif;z-index:99999';
    document.body.appendChild(bar);
  }
  bar.textContent = text;
}"""


def caption(page, text: str, hold: int = 1100) -> None:
    print(text)
    page.evaluate(_CAPTION_JS, text)
    page.wait_for_timeout(hold)


def stopped_by(stack) -> str:
    try:
        stack.check()
    except SubmitBlocked as blocked:
        return ", ".join(sorted({NAMES[event.layer] for event in blocked.events}))
    return ""


def record(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix="submit-guard-demo-"))
    videos = profile / "videos"
    executable = browser_executable()
    with ChallengeServer() as server, sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile / "profile"), headless=True, service_workers="block", accept_downloads=False,
            viewport=VIEWPORT, record_video_dir=str(videos), record_video_size=VIEWPORT,
            **({"executable_path": executable} if executable else {}))
        try:
            page = context.pages[0] if context.pages else context.new_page()
            stack = GuardStack(context)
            stack.before_goto()
            page.goto(server.url + "/")
            stack.after_load(page)
            assert stack.selfcheck(page), "self-check failed"
            caption(page, "Demo: a real run stops at the first block. This one keeps going to show all ten traps.", 2600)
            caption(page, "Guards on, self-check passed. The agent starts filling.", 1400)

            KEYS.type_text(page.locator("#name"), "Jordan Example")
            try:
                KEYS.send_key(page.locator("#name"), "Enter")
            except ForbiddenKey:
                caption(page, "1. Enter in a text field: refused by the keyboard guard")
            page.wait_for_timeout(2600)
            caption(page, f"4. A timer called requestSubmit(): stopped by the {stopped_by(stack)}")
            try:
                CLICKS.safe_click(page.locator("#next"))
            except ForbiddenClick:
                caption(page, "2. \"Next\" is a button with no type, so a submit button: refused by the click guard")
            KEYS.type_text(page.locator("#email"), "jordan@example.com")
            CLICKS.safe_click(page.locator("#city"))
            page.wait_for_timeout(400)
            caption(page, f"3. Leaving the email field called form.submit(): stopped by the {stopped_by(stack)}")
            KEYS.type_text(page.locator("#city"), "Springfield")
            page.wait_for_timeout(400)
            stopped_by(stack)
            caption(page, "9. The city lookup is where a service worker would POST: service workers are blocked")
            code = page.frame_locator("#referral").locator("#code")
            KEYS.type_text(code, "ABC123")
            KEYS.send_key(code, "Tab")
            page.wait_for_timeout(400)
            caption(page, f"5. The referral iframe posted its own form: stopped by the {stopped_by(stack)}")
            page.select_option("#source", "Friend")
            page.wait_for_timeout(400)
            caption(page, f"6. Choosing a source sent a fetch POST: stopped by the {stopped_by(stack)}")
            KEYS.type_text(page.locator("#why"), "I like the team.")
            page.wait_for_timeout(400)
            stopped_by(stack)
            caption(page, "7. Typing the answer fired sendBeacon: aborted by the network guard")
            with context.expect_page() as popup:
                CLICKS.safe_click(page.locator("#preview"))
            popup.value.wait_for_timeout(900)
            found = stopped_by(stack)
            popup.value.close()
            caption(page, f"8. \"Preview\" opened a popup that submits: stopped by the {found}")
            caption(page, "Nine traps sprung, nothing reached the server. Now the tenth.", 1600)
            CLICKS.safe_click(page.locator("#terms"))
            page.wait_for_timeout(1600)
            found = stopped_by(stack)
            caption(page, f"10. A meta refresh sent a GET to the confirm page. It got through; the {found} "
                          "caught it and the run stopped.", 3400)
            caption(page, "Captions are added by this demo script, not by the guards. A real run stops at the first "
                          "block.", 2600)
            stack.hand_over()
            video_path = Path(page.video.path())
        finally:
            context.close()
        received = list(server.received)
    print("server received:", received)
    target = out / "demo.webm"
    shutil.copyfile(video_path, target)
    shutil.rmtree(profile, ignore_errors=True)
    return target


def convert(webm: Path) -> None:
    if not shutil.which("ffmpeg"):
        return
    mp4, gif = webm.with_suffix(".mp4"), webm.with_suffix(".gif")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(mp4)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-vf",
                    "fps=8,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse",
                    str(gif)], check=True)


if __name__ == "__main__":
    convert(record(Path(sys.argv[1] if len(sys.argv) > 1 else "demo")))
