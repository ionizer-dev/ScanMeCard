import csv
import re
from html import escape
import sys
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw

INPUT_FILE = Path("contacts.csv")
OUTPUT_DIR = Path("output")
PHOTO_DIR = Path("photos")
DEFAULT_COLOR = "#1a1a1a"
CARDS_DIR = Path("docs/cards")
BASE_URL = "https://ionizer-dev.github.io/ScanMeCard/cards/"
CARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__NAME__</title>
<style>
  body { margin:0; font-family:Arial,Helvetica,sans-serif; background:#f2f2f2; }
  .card { max-width:420px; margin:0 auto; min-height:100vh; background:#fff; text-align:center; }
  .top { background:__COLOR__; height:120px; }
  .photo { width:150px; height:150px; border-radius:50%; border:5px solid #fff;
           object-fit:cover; margin-top:-75px; background:__COLOR__; }
  .initials { display:flex; align-items:center; justify-content:center; color:#fff; font-size:48px; }
  .photo-box { display:inline-block; }
  h1 { margin:12px 16px 4px; font-size:26px; color:#222; }
  .sub { color:#666; margin:0 16px 16px; }
  .rows { text-align:left; padding:0 24px; }
  .row { padding:12px 0; border-bottom:1px solid #eee; color:#333; word-break:break-word; }
  .row small { display:block; color:#888; font-size:12px; }
  .row a { color:__COLOR__; text-decoration:none; font-weight:bold; }
  .save { display:block; margin:24px; padding:14px; background:__COLOR__; color:#fff;
          text-decoration:none; border-radius:8px; font-size:18px; }
</style>
</head>
<body>
<div class="card">
  <div class="top"></div>
  __PHOTO__
  <h1>__NAME__</h1>
  <p class="sub">__SUBTITLE__</p>
  <div class="rows">__ROWS__</div>
  <a class="save" href="__VCF__" download>Save contact</a>
</div>
</body>
</html>
"""


def build_card_html(row, color, photo_b64, vcf_name):
    def g(key):
        return row.get(key, "").strip()

    first, last = g("first_name"), g("last_name")
    name = f"{first} {last}".strip()
    subtitle = ", ".join(x for x in [g("job_title"), g("organization")] if x)

    if photo_b64:
        photo = f'<img class="photo" src="data:image/jpeg;base64,{photo_b64}" alt="{escape(name)}">'
    else:
        initials = (first[:1] + last[:1]).upper()
        photo = f'<div class="photo-box"><div class="photo initials">{escape(initials)}</div></div>'

    def item(label, value_html):
        return f'<div class="row"><small>{label}</small>{value_html}</div>'

    rows = []
    if g("phone"):
        digits = re.sub(r"[^\d+]", "", g("phone"))
        rows.append(item("Phone", f'<a href="tel:{digits}">{escape(g("phone"))}</a>'))
    if g("email"):
        rows.append(item("Email", f'<a href="mailto:{escape(g("email"))}">{escape(g("email"))}</a>'))
    if g("website"):
        site = g("website")
        if not site.lower().startswith("http"):
            site = "https://" + site
        rows.append(item("Website", f'<a href="{escape(site)}">{escape(g("website"))}</a>'))
    address = ", ".join(x for x in [g("street"), g("city"), g("postal_code"), g("country")] if x)
    if address:
        rows.append(item("Address", escape(address)))
    if g("note"):
        rows.append(item("Note", escape(g("note"))))

    page = CARD_TEMPLATE
    for token, value in {
        "__NAME__": escape(name),
        "__COLOR__": color,
        "__PHOTO__": photo,
        "__SUBTITLE__": escape(subtitle),
        "__ROWS__": "".join(rows),
        "__VCF__": vcf_name,
    }.items():
        page = page.replace(token, value)
    return page

def esc(value):
    """Escape characters that have special meaning in a vCard."""
    return (value.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def build_vcard(row):
    first = row.get("first_name", "").strip()
    last = row.get("last_name", "").strip()
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"N:{esc(last)};{esc(first)}",
        f"FN:{esc((first + ' ' + last).strip())}",
    ]

    def add(prefix, key):
        value = row.get(key, "").strip()
        if value:
            lines.append(f"{prefix}:{esc(value)}")

    add("ORG", "organization")
    add("TITLE", "job_title")
    add("TEL;TYPE=CELL", "phone")
    add("EMAIL", "email")

    site = row.get("website", "").strip()
    if site:
        lines.append(f"URL:{site}")

    street = row.get("street", "").strip()
    city = row.get("city", "").strip()
    postal = row.get("postal_code", "").strip()
    country = row.get("country", "").strip()
    if any([street, city, postal, country]):
        lines.append(f"ADR:;;{esc(street)};{esc(city)};;{esc(postal)};{esc(country)}")

    add("NOTE", "note")
    lines.append("END:VCARD")
    return "\n".join(lines)


def valid_color(value):
    value = (value or "").strip()
    return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else DEFAULT_COLOR


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "contact"


def add_photo(qr_img, photo_path):
    """Place a round photo in the centre of the QR code."""
    qr_img = qr_img.convert("RGB")
    size = qr_img.size[0] // 5

    photo = Image.open(photo_path).convert("RGB")
    w, h = photo.size
    side = min(w, h)
    photo = photo.crop(((w - side) // 2, (h - side) // 2,
                        (w + side) // 2, (h + side) // 2)).resize((size, size))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)

    pad = size // 10
    bg_size = size + pad * 2
    bg_mask = Image.new("L", (bg_size, bg_size), 0)
    ImageDraw.Draw(bg_mask).ellipse((0, 0, bg_size, bg_size), fill=255)
    white = Image.new("RGB", (bg_size, bg_size), "white")

    cx = (qr_img.size[0] - bg_size) // 2
    cy = (qr_img.size[1] - bg_size) // 2
    qr_img.paste(white, (cx, cy), bg_mask)
    qr_img.paste(photo, (cx + pad, cy + pad), mask)
    return qr_img


def make_qr(vcard, color, path, photo_path=None):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H,
                       box_size=12, border=3)
    qr.add_data(vcard)
    qr.make(fit=True)
    img = qr.make_image(fill_color=color, back_color="white").convert("RGB")
    if photo_path:
        img = add_photo(img, photo_path)
    img.save(path)


def main():
    if not INPUT_FILE.exists():
        sys.exit("contacts.csv not found. Create it first.")

    OUTPUT_DIR.mkdir(exist_ok=True)
    count = 0
    with INPUT_FILE.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
            if not name:
                continue

            photo_path = None
            photo_name = row.get("photo", "").strip()
            if photo_name:
                candidate = PHOTO_DIR / photo_name
                if candidate.exists():
                    photo_path = candidate
                else:
                    print(f"Photo not found for {name}: {candidate}")

            out = OUTPUT_DIR / f"{slugify(name)}.png"
            make_qr(build_vcard(row), valid_color(row.get("color", "")), out, photo_path)
            print("Created", out)
            count += 1

    print(f"Done: {count} QR code(s) in '{OUTPUT_DIR}/'")


if __name__ == "__main__":
    main()