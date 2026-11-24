"""Custom manager identity (spec ch.43) - engine side only, no UI.

- name: stored per career in career_info.manager_name (validated)
- photo: validated (magic bytes + size cap + real decode + pixel cap), re-encoded (strips EXIF/metadata),
  stored INSIDE <saves>/<career_id>_assets/ only. Never references external paths, never uses the network.
- reputation: single integer 1..100 in manager_profile. There is deliberately NO history table.

The parent wires these into CareerManager; nothing here touches CareerManager.
"""
import os
import re
import shutil
import unicodedata
from pathlib import Path

MAX_NAME_LEN = 40
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_PHOTO_PIXELS = 40_000_000
PHOTO_SIZE = (800, 1000)   # 4:5 portrait
THUMB_SIZE = (96, 120)
BG = (27, 31, 34)          # SURFACE_PRIMARY, used to flatten transparency

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ALLOWED_PUNCT = {"'", "’", "-", "."}


class ManagerError(ValueError):
    pass


def ensure_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS manager_profile(
        id INTEGER PRIMARY KEY CHECK(id=1), reputation INTEGER NOT NULL DEFAULT 30
        CHECK(reputation BETWEEN 1 AND 100), current_club_id INTEGER,
        has_photo INTEGER NOT NULL DEFAULT 0, photo_version INTEGER NOT NULL DEFAULT 0,
        last_offer_check TEXT)""")
    con.commit()


# ---------------------------------------------------------------- name
def validate_name(raw):
    """Return the cleaned name or raise ManagerError. Strict on purpose: letters/marks/space/' - . only."""
    if not isinstance(raw, str):
        raise ManagerError("name must be text")
    s = unicodedata.normalize("NFC", raw)
    if any(unicodedata.category(ch) == "Cc" for ch in s):  # newline/tab/NUL etc.: refuse, do not silently fold
        raise ManagerError("control characters are not allowed")
    s = re.sub(r"\s+", " ", s.strip())
    if not s:
        raise ManagerError("name is empty")
    if len(s) > MAX_NAME_LEN:
        raise ManagerError("name too long")
    letters = 0
    for ch in s:
        cat = unicodedata.category(ch)
        if cat.startswith("L"):
            letters += 1
        elif cat.startswith("M") or ch == " " or ch in _ALLOWED_PUNCT:
            continue
        else:  # control (Cc), format/bidi overrides (Cf), digits, symbols, separators, private use...
            raise ManagerError(f"character not allowed: U+{ord(ch):04X}")
    if letters == 0:
        raise ManagerError("name needs at least one letter")
    return s


def set_name(con, raw):
    name = validate_name(raw)
    with con:
        con.execute("UPDATE career_info SET manager_name=?", (name,))
    return name


def get_name(con):
    return con.execute("SELECT manager_name FROM career_info").fetchone()[0]


def mtext(con, template, **extra):
    """Replace {manager} (and any extra tokens) in event text with the user's chosen manager name.
    Plain replace, not str.format: names/templates with braces cannot break it."""
    out = template.replace("{manager}", get_name(con))
    for k, v in extra.items():
        out = out.replace("{" + k + "}", str(v))
    return out


# ---------------------------------------------------------------- profile / reputation
def ensure_profile(con, start_reputation=None):
    ensure_schema(con)
    row = con.execute("SELECT * FROM manager_profile").fetchone()
    if row:
        return dict(row)
    cid = con.execute("SELECT club_id FROM career_info").fetchone()[0]
    if start_reputation is None:
        r = con.execute("SELECT reputation FROM world.clubs WHERE id=?", (cid,)).fetchone()
        start_reputation = max(10, min(90, int(round((r[0] if r else 50) * 0.7))))
    with con:
        con.execute("INSERT INTO manager_profile(id,reputation,current_club_id) VALUES(1,?,?)",
                    (int(start_reputation), cid))
    return dict(con.execute("SELECT * FROM manager_profile").fetchone())


def get_profile(con):
    return ensure_profile(con)


def set_reputation(con, value):
    ensure_profile(con)
    v = max(1, min(100, int(value)))
    with con:
        con.execute("UPDATE manager_profile SET reputation=?", (v,))
    return v


def add_reputation(con, delta):
    return set_reputation(con, ensure_profile(con)["reputation"] + int(delta))


# ---------------------------------------------------------------- assets (photo)
def assets_dir(saves_dir, career_id):
    if not _ID_RE.fullmatch(str(career_id)):
        raise ManagerError("bad career id")
    return Path(saves_dir) / f"{career_id}_assets"


def _career_id(con):
    return con.execute("SELECT career_id FROM career_info").fetchone()[0]


def _sniff(data):
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


_EXT_KIND = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp"}


def validate_photo_bytes(data, declared_name=None, max_bytes=MAX_PHOTO_BYTES, max_pixels=MAX_PHOTO_PIXELS):
    """Return the Pillow image (loaded, RGB-flattened) or raise ManagerError."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ManagerError("empty file")
    if len(data) > max_bytes:
        raise ManagerError("file too large")
    kind = _sniff(bytes(data[:16]))
    if kind is None:
        raise ManagerError("not a JPG/PNG/WebP image")
    if declared_name is not None:
        ext = os.path.splitext(str(declared_name))[1].lower()
        if _EXT_KIND.get(ext) != kind:
            raise ManagerError("file extension does not match its real type")
    try:
        from PIL import Image, ImageOps
    except ImportError as e:  # documented hook: without Pillow only validation of the container is possible
        raise ManagerError("image decoder (Pillow) not available") from e
    import io
    try:
        im = Image.open(io.BytesIO(bytes(data)))
        if im.width * im.height > max_pixels:
            raise ManagerError("image dimensions too large")
        if im.width < 16 or im.height < 16:
            raise ManagerError("image too small")
        im.load()
        im = ImageOps.exif_transpose(im)
    except ManagerError:
        raise
    except Exception as e:
        raise ManagerError("corrupt or unreadable image") from e
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, BG)
        bg.paste(im, mask=im.split()[-1])
        return bg
    return im.convert("RGB")


def _crop_4x5(im, crop):
    """crop = (x0,y0,x1,y1) as fractions 0..1 of the image; None = centred 4:5 crop. The box is forced to 4:5."""
    w, h = im.size
    if crop is None:
        bw, bh = (h * 4 / 5, h) if w / h > 4 / 5 else (w, w * 5 / 4)
        cx, cy = w / 2, h / 2
    else:
        x0, y0, x1, y1 = crop
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ManagerError("bad crop box")
        cx, cy = (x0 + x1) / 2 * w, (y0 + y1) / 2 * h
        bw, bh = (x1 - x0) * w, (y1 - y0) * h
        if bw / bh > 4 / 5:
            bw = bh * 4 / 5
        else:
            bh = bw * 5 / 4
    bw, bh = min(bw, w), min(bh, h)
    left = max(0, min(w - bw, cx - bw / 2))
    top = max(0, min(h - bh, cy - bh / 2))
    return im.crop((int(left), int(top), int(left + bw), int(top + bh)))


def set_photo(con, saves_dir, source, crop=None, declared_name=None,
              max_bytes=MAX_PHOTO_BYTES, max_pixels=MAX_PHOTO_PIXELS):
    """source = bytes or a file path. Stores photo.jpg + thumb.jpg inside this career's own assets folder.
    The user's original file is never referenced afterwards."""
    if isinstance(source, (str, os.PathLike)):
        p = Path(source)
        if declared_name is None:
            declared_name = p.name
        if not p.is_file():
            raise ManagerError("file not found")
        if p.stat().st_size > max_bytes:  # check size BEFORE reading
            raise ManagerError("file too large")
        data = p.read_bytes()
    else:
        data = bytes(source)
    im = validate_photo_bytes(data, declared_name, max_bytes, max_pixels)
    from PIL import Image
    im = _crop_4x5(im, crop)
    full = im.resize(PHOTO_SIZE, Image.LANCZOS) if im.size[0] > PHOTO_SIZE[0] else im
    thumb = im.resize(THUMB_SIZE, Image.LANCZOS)
    d = assets_dir(saves_dir, _career_id(con))
    d.mkdir(parents=True, exist_ok=True)
    for name, img, q in (("photo.jpg", full, 90), ("thumb.jpg", thumb, 85)):
        tmp = d / (name + ".tmp")
        img.save(tmp, "JPEG", quality=q, optimize=True)  # re-encode: drops EXIF/ICC/any embedded payload
        os.replace(tmp, d / name)
    ensure_schema(con)
    ensure_profile(con)
    with con:
        con.execute("UPDATE manager_profile SET has_photo=1, photo_version=photo_version+1")
    return photo_paths(con, saves_dir)


def remove_photo(con, saves_dir):
    """Back to the default silhouette (the UI draws it when has_photo is 0)."""
    d = assets_dir(saves_dir, _career_id(con))
    for name in ("photo.jpg", "thumb.jpg"):
        try:
            (d / name).unlink()
        except FileNotFoundError:
            pass
    ensure_profile(con)
    with con:
        con.execute("UPDATE manager_profile SET has_photo=0, photo_version=photo_version+1")


def photo_paths(con, saves_dir):
    """{'has_photo': bool, 'photo': path|None, 'thumb': path|None, 'version': int}; falls back to default if files vanished."""
    prof = ensure_profile(con)
    d = assets_dir(saves_dir, _career_id(con))
    ph, th = d / "photo.jpg", d / "thumb.jpg"
    ok = bool(prof["has_photo"]) and ph.is_file() and th.is_file()
    return {"has_photo": ok, "photo": str(ph) if ok else None, "thumb": str(th) if ok else None,
            "version": prof["photo_version"]}


def delete_assets(saves_dir, career_id):
    """Delete ONLY this career's assets folder (call when a career is deleted)."""
    d = assets_dir(saves_dir, career_id)
    root = Path(saves_dir).resolve()
    if d.exists():
        if d.resolve().parent != root:
            raise ManagerError("refusing to delete outside the saves folder")
        shutil.rmtree(d)
