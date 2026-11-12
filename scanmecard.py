import base64
import csv
import io
import re
import sys
from html import escape
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
<meta name="theme-color" content="__COLOR__">
<meta property="og:title" content="__NAME__">
<meta property="og:description" content="__DESC__">
<title>__NAME__</title>
<style>
  :root { --accent:__COLOR__; }
  * { box-sizing:border-box; }
  body { margin:0; background:#f2f2f2; color:#222;
         font-family:-apple-system,"Segoe UI",Roboto,Arial,sans-serif; }
  .card { max-width:420px; margin:0 auto; min-height:100vh; background:#fff; }
  .top { height:120px; background:var(--accent); }
  .head { text-align:center; padding:0 24px 20px; }
  .photo { display:block; width:148px; height:148px; border-radius:50%; margin:-74px auto 0;
           border:5px solid #fff; object-fit:cover; background:var(--accent); }
  .initials { display:flex; align-items:center; justify-content:center;
              color:#fff; font-size:46px; letter-spacing:1px; }
  h1 { margin:16px 0 6px; font-size:25px; line-height:1.25; font-weight:700; }
  .title { margin:0; color:#555; font-size:15px; line-height:1.45; }
  .org { margin:4px 0 0; color:#888; font-size:15px; }
  .rows { padding:0 24px; }
  .row { display:block; padding:15px 0; border-top:1px solid #ececec;
         color:inherit; text-decoration:none; word-break:break-word; }
  .row small { display:block; margin-bottom:4px; color:#8a8a8a; font-size:11px;
               letter-spacing:.08em; text-transform:uppercase; }
  .row span { font-size:16px; line-height:1.4; }
  a.row span { color:var(--accent); font-weight:600; }
  .save { display:block; margin:24px; padding:15px; background:var(--accent); color:#fff;
          text-align:center; text-decoration:none; font-size:17px; font-weight:600;
          border-radius:8px; }
</style>
</head>
<body>
<div class="card">
  <div class="top"></div>
  <div class="head">
    __PHOTO__
    <h1>__NAME__</h1>
    __TITLE__
    __ORG__
  </div>
  <div class="rows">__ITEMS__</div>
  <a class="save" href="__VCF__" download>Save contact</a>
</div>
</body>
</html>
"""


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


def photo_to_base64(photo_path, size=256):
    """Make a small square JPEG of the photo and encode it as text."""
    img = Image.open(photo_path).convert("RGB")
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2,
                    (w + side) // 2, (h + side) // 2)).resize((size, size))
    buffer = io.BytesIO()
    img.save(buffer, "JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


def fold(line):
    """vCard lines should be at most 75 characters; longer ones are folded."""
    return "\r\n ".join(line[i:i + 74] for i in range(0, len(line), 74))


def save_vcf(vcard, photo_path, path):
    lines = vcard.split("\n")
    if photo_path:
        lines.insert(-1, "PHOTO;ENCODING=b;TYPE=JPEG:" + photo_to_base64(photo_path))
    text = "\r\n".join(fold(line) for line in lines) + "\r\n"
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(text)


def build_card_html(row, color, photo_b64, vcf_name):
    def g(key):
        return row.get(key, "").strip()

    def link(value):
        return value if value.lower().startswith("http") else "https://" + value

    first, last = g("first_name"), g("last_name")
    name = f"{first} {last}".strip()
    title, org = g("job_title"), g("organization")

    if photo_b64:
        photo = f'<img class="photo" src="data:image/jpeg;base64,{photo_b64}" alt="{escape(name)}">'
    else:
        initials = (first[:1] + last[:1]).upper()
        photo = f'<div class="photo initials">{escape(initials)}</div>'

    def item(label, value_html, href=None):
        inner = f"<small>{label}</small><span>{value_html}</span>"
        if href:
            return f'<a class="row" href="{href}">{inner}</a>'
        return f'<div class="row">{inner}</div>'

    items = []

    phone = g("phone")
    if phone:
        items.append(item("Phone", escape(phone), "tel:" + re.sub(r"[^\d+]", "", phone)))

    email = g("email")
    if email:
        items.append(item("Email", escape(email), "mailto:" + escape(email)))

    website = g("website")
    if website:
        items.append(item("Website", escape(website), escape(link(website))))

    linkedin = g("linkedin")
    if linkedin:
        items.append(item("LinkedIn", escape(linkedin), escape(link(linkedin))))

    address = ", ".join(x for x in [g("street"), g("city"), g("postal_code"), g("country")] if x)
    if address:
        items.append(item("Address", escape(address)))

    if g("note"):
        items.append(item("Note", escape(g("note"))))

    replacements = {
        "__NAME__": escape(name),
        "__DESC__": escape(" - ".join(x for x in [title, org] if x)),
        "__COLOR__": color,
        "__PHOTO__": photo,
        "__TITLE__": f'<p class="title">{escape(title)}</p>' if title else "",
        "__ORG__": f'<p class="org">{escape(org)}</p>' if org else "",
        "__ITEMS__": "".join(items),
        "__VCF__": vcf_name,
    }

    page = CARD_TEMPLATE
    for token, value in replacements.items():
        page = page.replace(token, value)
    return page


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


def make_qr(data, color, path, photo_path=None):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H,
                       box_size=12, border=3)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color=color, back_color="white").convert("RGB")
    if photo_path:
        img = add_photo(img, photo_path)
    img.save(path)


def main():
    if not INPUT_FILE.exists():
        sys.exit("contacts.csv not found. Create it first.")

    OUTPUT_DIR.mkdir(exist_ok=True)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    count = 0

    with INPUT_FILE.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
            if not name:
                continue

            slug = slugify(name)
            color = valid_color(row.get("color", ""))

            photo_path = None
            photo_name = row.get("photo", "").strip()
            if photo_name:
                candidate = PHOTO_DIR / photo_name
                if candidate.exists():
                    photo_path = candidate
                else:
                    print(f"Photo not found for {name}: {candidate}")

           
            save_vcf(build_vcard(row), photo_path, CARDS_DIR / f"{slug}.vcf")

            
            photo_b64 = photo_to_base64(photo_path, 300) if photo_path else ""
            page = build_card_html(row, color, photo_b64, f"{slug}.vcf")
            (CARDS_DIR / f"{slug}.html").write_text(page, encoding="utf-8")

           
            make_qr(BASE_URL + f"{slug}.html", color, OUTPUT_DIR / f"{slug}.png", photo_path)

            print("Created card and QR for", name)
            count += 1

    print(f"Done: {count} card(s). Pages are in '{CARDS_DIR}/', QR codes in '{OUTPUT_DIR}/'")


if __name__ == "__main__":
    main()