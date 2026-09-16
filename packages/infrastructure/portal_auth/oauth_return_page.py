"""The page a browser lands on after a sign-in that started in WhatsApp.

Not the portal: the person was never there and has no reason to be. A calm
card on the leaves background, one sentence, and a way back to the chat.
"""

from __future__ import annotations

import html

# The WhatsApp glyph, drawn in the button's own colour.
_WHATSAPP_ICON = (
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M17.47 14.38c-.3-.15-1.76-.87-2.03-.97'
    "-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.07-.3-.15-1.26-.46-2.39-1.47-.88-.79-1.48-1.76-1.65"
    "-2.06-.17-.3-.02-.46.13-.6.13-.14.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.02-.52-.08-.15-.67-1.62-.92-2.22-.24"
    "-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.8.37-.27.3-1.04 1.02-1.04 2.48s1.07 2.88 1.21 3.07c.15.2 2.1 3.2 5.08 4.49"
    ".71.3 1.27.49 1.7.62.72.23 1.37.2 1.88.12.57-.08 1.76-.72 2.01-1.41.25-.7.25-1.29.17-1.41-.07-.13-.27-.2-.57-.35m"
    "-5.42 7.4h-.01a9.87 9.87 0 0 1-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 0 1-1.51-5.26c0-5.45 4.44-9.88"
    " 9.89-9.88 2.64 0 5.12 1.03 6.99 2.9a9.82 9.82 0 0 1 2.89 6.99c0 5.45-4.44 9.88-9.88 9.88m8.41-18.3A11.82 11.82 0 0 "
    "0 12.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.3-1.65a11.88 11.88 0 0 0 5.68 1.45h.01c6.55 0 "
    '11.89-5.34 11.89-11.89 0-3.18-1.24-6.16-3.48-8.41"/></svg>'
)

_STYLE = """
:root{--ink:#132038;--ink-soft:#4a5468;--paper:#f6f1e8;--serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%}
body{min-height:100vh;min-height:100dvh;display:flex;flex-direction:column;align-items:center;
  padding:max(2.5rem,env(safe-area-inset-top)) 1rem 3rem;color:var(--ink);font-family:var(--serif);
  background:var(--paper) url("/assets/connected-bg-mobile.webp") center / cover no-repeat;
  -webkit-font-smoothing:antialiased;line-height:1.4}
@media (min-width:48rem){body{background-image:url("/assets/connected-bg-desktop.webp");justify-content:center;padding-top:2rem}}
.brand{display:flex;flex-direction:column;align-items:center;margin:0 0 2.2rem;text-decoration:none;color:inherit}
.brand img{width:2.5rem;height:auto;margin-bottom:.1rem}
.brand span{font-size:2.35rem;letter-spacing:-.01em}
.card{width:min(100%,24.5rem);padding:1.75rem 1.9rem 2.1rem;text-align:center;border-radius:1.75rem;
  background:rgba(255,255,255,.5);border:1px solid rgba(255,255,255,.7);
  box-shadow:0 30px 70px rgba(19,32,56,.08);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
.robot{display:block;width:11.5rem;height:auto;margin:0 auto .6rem}
h1{margin:0 0 .9rem;font-size:clamp(1.9rem,8.4vw,2.35rem);font-weight:600;line-height:1.1;letter-spacing:-.02em}
p{margin:0 auto;max-width:18rem;font-size:1.1rem;color:var(--ink-soft)}
.back{display:flex;align-items:center;justify-content:center;gap:.75rem;margin:1.9rem 0 1.3rem;padding:1.05rem 1.2rem;
  border-radius:999px;color:#fff;text-decoration:none;font:500 1.12rem/1.2 "Manrope","Segoe UI",system-ui,-apple-system,sans-serif;
  background:linear-gradient(100deg,#2c7f86,#4f9a7e 70%,#62a878);box-shadow:0 14px 30px rgba(44,127,134,.25)}
.back svg{width:1.6rem;height:1.6rem}
.back:active{transform:translateY(1px)}
.hint{font-size:.95rem;max-width:none}
"""


def render_oauth_return_page(*, ok: bool, provider_label: str, message: str, whatsapp_number: str) -> str:
    """Return the whole page. ``message`` replaces the all-set line when there is more to say."""

    label = html.escape(provider_label or "Your account")
    title = "Connected" if ok else "Not connected"
    heading = f"{label} connected!" if ok else f"{label} isn&#8217;t connected yet"
    line = html.escape(message) if message else "You&#8217;re all set. Your conversation is waiting for you in WhatsApp."
    robot = (
        '<img class="robot" src="/assets/robot-thumbs-up.webp" width="368" height="368" alt="" />'
        if ok else ""
    )
    if whatsapp_number:
        back = (
            f'<a class="back" href="https://wa.me/{html.escape(whatsapp_number)}">{_WHATSAPP_ICON}Back to WhatsApp</a>'
            '<p class="hint">You can close this page after returning.</p>'
        )
    else:
        back = '<p class="hint" style="margin-top:1.6rem">You can close this page and go back to WhatsApp.</p>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="theme-color" content="#f6f1e8">'
        f"<title>{title} - Assistyca</title>"
        '<link rel="icon" type="image/png" href="/assets/Robot-200.png">'
        '<link rel="preload" as="font" type="font/woff2" href="/assets/manrope-medium.woff2" crossorigin>'
        '<style>@font-face{font-family:"Manrope";src:url("/assets/manrope-medium.woff2") format("woff2");'
        f"font-weight:500;font-display:swap}}{_STYLE}</style></head><body>"
        '<a class="brand" href="/"><img src="/assets/sprout.webp" width="120" height="120" alt="" />'
        "<span>Assistyca</span></a>"
        f'<main class="card">{robot}<h1>{heading}</h1><p>{line}</p>{back}</main>'
        "</body></html>"
    )
