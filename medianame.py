#!/usr/bin/env python3
"""
Clean up messy movie/TV filenames and folder names into a simple form:
  Movies:  Title (Year).ext                         (no parens if no year found)
  TV:      Show Name (Year)/Season N/Show Name - Episode Title - S01E02.ext
           (no episode title segment if none could be found; no year if none found)
Recurses up to 3 levels deep (root, +1, +2) for discovering files. Dry-run by
default; pass -f/--apply to actually rename/move things.

Files with a genuine SxxEyy code are organized into season folders. A file
with no SxxEyy code but a bare episode number (" - 05"), sitting in a folder
that already looks like a show folder, is treated as a flat/miniseries
episode (Show - E05.ext, no season folder) - and a leading release-group tag
like "[AnimeRG] " that doesn't match the show name is stripped. Anything else
with no season/episode signal at all and no matching folder context is left
alone rather than guessed at.
"""
import argparse
import os
import re
import sys

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".wmv", ".flv", ".webm", ".ts", ".m2ts"}
SUB_EXTS = {".srt", ".ass", ".ssa", ".sub", ".vtt", ".idx"}
MEDIA_EXTS = VIDEO_EXTS | SUB_EXTS

LANG_CODES = {
    "en", "eng", "english", "fr", "fre", "fra", "french", "es", "spa", "spanish",
    "de", "ger", "deu", "german", "it", "ita", "italian", "pt", "por", "portuguese",
    "nl", "dut", "nld", "dutch", "ru", "rus", "russian", "ja", "jp", "jpn", "japanese",
    "ko", "kor", "korean", "zh", "chi", "zho", "chinese", "ar", "ara", "arabic",
    "sv", "swe", "swedish", "da", "dan", "danish", "no", "nor", "norwegian",
    "fi", "fin", "finnish", "pl", "pol", "polish", "tr", "tur", "turkish",
    "cs", "cze", "ces", "czech", "el", "gre", "ell", "greek", "he", "heb", "hebrew",
    "hi", "hin", "hindi", "th", "tha", "thai", "vi", "vie", "vietnamese",
    "id", "ind", "indonesian", "ro", "rum", "ron", "romanian", "hu", "hun", "hungarian",
    "forced", "sdh",
}

QUALITY_KEYWORDS = [
    "2160p", "1080p", "720p", "480p", "4k", "8k", "uhd", "bluray", "blu-ray", "brrip",
    "bdrip", "bd25", "bd50", "webrip", "web-dl", "webdl", "web", "hdtv", "pdtv",
    "dvdrip", "dvdscr", "camrip", "hdcam", "hdr10plus", "hdr10", "hdr", "dv",
    "dolby vision", "x264", "x265", "h264", "h265", "hevc", "avc", "xvid", "divx",
    "aac5", "aac", "ac3", "ac-3", "dts-hd", "dts", "ddp5", "ddp", "dd5", "dd7",
    "truehd", "flac", "opus", "10bit", "8bit", "remastered", "extended", "theatrical",
    "criterion", "unrated", "uncut", "proper", "repack", "internal", "limited",
    "japanese", "subbed", "dubbed", "multi", "dual audio", "nf", "amzn", "dsnp",
    "hulu", "atvp", "yts", "rarbg", "evo", "sparks", "hybrid", "imax", "complete",
]
_KEYWORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in QUALITY_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2}(?:-(?:19|20)\d{2})?)(?!\d)")
TV_RE = re.compile(r"[Ss](\d{1,2})[Ee](\d{2,4})")
LEADING_NUM_RE = re.compile(r"^\s*\d{1,3}[.\)]\s+")
TRAILING_JUNK_RE = re.compile(r"[\s\-\(\[,.]+$")
LEADING_SEP_RE = re.compile(r"^[\s.\_\-]+")
LEADING_DUP_EP_NUM_RE = re.compile(r"^\(\s*\d{1,3}\s*\)\s*[-\s]*")
SEASON_DIR_RE = re.compile(r"^season\s*0*(\d{1,3})$", re.IGNORECASE)
LEADING_BRACKET_TAG_RE = re.compile(r"^\[[^\]]*\]\s*")
FLAT_EP_RE = re.compile(r"^[\s._-]*[Ee]?(\d{1,3})(?!\d)[\s._-]*")


def strip_trailing_junk(s):
    return TRAILING_JUNK_RE.sub("", s).strip()


def normalize_title(raw):
    s = raw.replace(".", " ").replace("_", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return strip_trailing_junk(s)


def strip_quality_tail(norm):
    """norm must already be separator-normalized and whitespace-collapsed.
    Cuts off a trailing quality/codec tag if found. Returns '' if the result
    would have unbalanced brackets (i.e. we can't confidently parse it)."""
    kw_match = _KEYWORD_RE.search(norm)
    title = strip_trailing_junk(norm[: kw_match.start()]) if kw_match else strip_trailing_junk(norm)
    if title.count("(") != title.count(")") or title.count("[") != title.count("]"):
        return ""
    return title


def norm_key(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def clean_stem(stem):
    """Clean a movie/misc filename or directory stem (no extension)."""
    stem = LEADING_NUM_RE.sub("", stem)

    year_matches = list(YEAR_RE.finditer(stem))
    if year_matches:
        last = year_matches[-1]
        title_raw = stem[: last.start()]
        year = last.group(1)
        title = normalize_title(title_raw)
        if title:
            return f"{title} ({year})"
        return stem  # nothing before the year - leave untouched rather than guess

    norm = re.sub(r"[._]+", " ", stem)
    norm = re.sub(r"\s+", " ", norm).strip()
    title = strip_quality_tail(norm)
    return title if title else stem


def split_ext_lang(name):
    """Returns (stem, lang_suffix_with_dot_or_empty, ext_lowercase)."""
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    lang = ""
    if ext in SUB_EXTS:
        stem2, maybe_lang = os.path.splitext(stem)
        if maybe_lang.lower().lstrip(".") in LANG_CODES and stem2:
            lang = maybe_lang.lower()
            stem = stem2
    return stem, lang, ext


def clean_filename(name):
    stem, lang, ext = split_ext_lang(name)
    return f"{clean_stem(stem)}{lang}{ext}"


def clean_dirname(name):
    return clean_stem(name)


LEADING_YEAR_RE = re.compile(r"^[\s._-]*\(\s*((?:19|20)\d{2})\s*\)[\s._-]*|^[\s._-]*((?:19|20)\d{2})(?!\d)[\s._-]*")


def extract_and_strip_year(text):
    """A show's year annotation, if present, always sits immediately after the
    show name - never buried inside an episode title (which might itself
    contain a number that looks like a year, e.g. "...in 2000 Years..."). So
    only strip a year found at the very start of text, not searched anywhere
    within it. Returns (year_or_None, text_with_leading_year_removed)."""
    m = LEADING_YEAR_RE.match(text)
    if m:
        year = m.group(1) or m.group(2)
        return year, text[m.end():]
    return None, text


def extract_episode_title(remainder):
    remainder = LEADING_SEP_RE.sub("", remainder)
    remainder = LEADING_DUP_EP_NUM_RE.sub("", remainder)
    norm = remainder.replace(".", " ").replace("_", " ")
    norm = re.sub(r"\s+", " ", norm).strip()
    return strip_quality_tail(norm)


def build_prefix_regex(hint):
    words = [w for w in re.split(r"[\s._-]+", hint) if w]
    if not words:
        return None
    parts = [re.escape(w) for w in words]
    return re.compile(r"^" + r"[\s._-]+".join(parts) + r"[\s._-]*", re.IGNORECASE)


def parse_tv(stem, show_hint=None):
    """Returns {'show','year','season','episode','title'} or None if this
    doesn't look like a TV episode (no SxxEyy code found).

    show_hint, if given, is the name of a show/season folder this file
    already lives in. We use it to split "show" from "episode title"
    unambiguously - important because once episode titles are placed before
    the SxxEyy code (Show - Title - S01E02), a pure regex re-parse of an
    already-organized file can't otherwise tell where the show name ends and
    the episode title begins. It also lets us recover an episode title that
    lands *after* the code, for not-yet-organized files sitting in a folder
    that was set up by hand or a previous partial run.

    Two extra things the hint unlocks: a leading release-group tag like
    "[AnimeRG] " that doesn't match the show name is stripped and ignored
    (the folder name is trusted over the tag); and a bare episode number with
    no SxxEyy code at all ("Berserk - 01") is treated as a flat/miniseries
    episode (season=None), matching the no-season-folder convention used for
    single-season shows like Chernobyl or Neon Genesis Evangelion."""
    stem = LEADING_NUM_RE.sub("", stem)

    if show_hint:
        prefix_re = build_prefix_regex(show_hint)
        prefix_match = prefix_re.match(stem) if prefix_re else None
        tag_was_stripped = False
        if not prefix_match and prefix_re and LEADING_BRACKET_TAG_RE.match(stem):
            # A leading release-group tag that doesn't match the show name -
            # trust the folder, drop the tag, and retry.
            stripped = LEADING_BRACKET_TAG_RE.sub("", stem, count=1)
            prefix_match_stripped = prefix_re.match(stripped)
            if prefix_match_stripped:
                stem = stripped
                prefix_match = prefix_match_stripped
                tag_was_stripped = True
        if prefix_match:
            remainder = stem[prefix_match.end():]
            tv_match = TV_RE.search(remainder)
            if tv_match:
                season = int(tv_match.group(1))
                episode = tv_match.group(2).zfill(2)
                before_text = remainder[: tv_match.start()]
                year, before_text = extract_and_strip_year(before_text)
                before_title = extract_episode_title(before_text)
                after_title = extract_episode_title(remainder[tv_match.end():])
                episode_title = before_title or after_title
                return {
                    "show": show_hint,
                    "year": year,
                    "season": season,
                    "episode": episode,
                    "title": episode_title,
                }
            flat_match = FLAT_EP_RE.match(remainder)
            if flat_match:
                episode = flat_match.group(1).zfill(2)
                episode_title = extract_episode_title(remainder[flat_match.end():])
                # Only reformat if we actually found junk to remove (a stripped
                # tag) or there's nothing else here to lose (already just the
                # bare number) - otherwise this is a fine, pre-existing style
                # (e.g. Evangelion's "Show E01 Title.mkv") that wasn't asked
                # to be touched, so leave it alone.
                if tag_was_stripped or not episode_title:
                    return {
                        "show": show_hint,
                        "year": None,
                        "season": None,
                        "episode": episode,
                        "title": episode_title,
                    }

    m = TV_RE.search(stem)
    if not m:
        return None
    show_raw = stem[: m.start()]
    season = int(m.group(1))
    episode = m.group(2).zfill(2)

    year = None
    year_matches = list(YEAR_RE.finditer(show_raw))
    if year_matches:
        last = year_matches[-1]
        year = last.group(1)
        show_raw = show_raw[: last.start()]

    show_title = normalize_title(show_raw)
    if not show_title:
        return None

    episode_title = extract_episode_title(stem[m.end():])
    return {"show": show_title, "year": year, "season": season, "episode": episode, "title": episode_title}


def find_dir_show_hint(file_path):
    """Purely structural (no filename parsing): if this file already sits
    inside what looks like a show folder, or a Season N folder under one,
    return that show folder's name (year stripped) as a parsing hint."""
    parent = os.path.dirname(file_path)
    parent_name = os.path.basename(parent)

    if SEASON_DIR_RE.match(parent_name):
        grandparent = os.path.dirname(parent)
        gp_name = TRAILING_YEAR_PAREN_RE.sub("", os.path.basename(grandparent)).strip()
        return gp_name or None

    candidate = TRAILING_YEAR_PAREN_RE.sub("", parent_name).strip()
    return candidate or None


def find_tv_base_dir(file_path, show_key):
    """Where should the Show (Year)/Season N/ tree live? Reuses an existing
    show folder (directly, or one level up through a Season folder) if found,
    otherwise anchors a new one at the file's current directory."""
    parent = os.path.dirname(file_path)
    parent_name = os.path.basename(parent)

    season_match = SEASON_DIR_RE.match(parent_name)
    if season_match:
        grandparent = os.path.dirname(parent)
        gp_name = os.path.basename(grandparent)
        if show_key and show_key in norm_key(gp_name):
            return os.path.dirname(grandparent), grandparent
        return os.path.dirname(parent), None

    if show_key and show_key in norm_key(parent_name):
        return os.path.dirname(parent), parent

    return parent, None


TRAILING_YEAR_PAREN_RE = re.compile(r"\s*\((?:19|20)\d{2}\)$")


def compute_show_folder_name(existing_dir, derived_title, year):
    if existing_dir:
        base_name = os.path.basename(existing_dir)
        base_name_no_year = TRAILING_YEAR_PAREN_RE.sub("", base_name)
        if norm_key(base_name_no_year) == norm_key(derived_title):
            # Already just the show title, maybe with a year already appended
            # (from a prior run or manual curation) - keep it, don't re-derive.
            if TRAILING_YEAR_PAREN_RE.search(base_name):
                return base_name
            if year:
                return f"{base_name} ({year})"
            return base_name
        # existing folder name has extra cruft beyond the show title - replace
        # wholesale, but keep an existing year annotation if this file didn't
        # supply one itself.
        if year:
            return f"{derived_title} ({year})"
        existing_year = TRAILING_YEAR_PAREN_RE.search(base_name)
        if existing_year:
            return f"{derived_title}{existing_year.group(0)}"
    return f"{derived_title} ({year})" if year else derived_title


def scan(root, max_depth):
    all_files = []
    all_dirs = []

    def walk(path, depth):
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name)
        except (PermissionError, FileNotFoundError):
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                all_dirs.append(entry.path)
                if depth < max_depth:
                    walk(entry.path, depth + 1)
            elif entry.is_file():
                if os.path.splitext(entry.name)[1].lower() in MEDIA_EXTS:
                    all_files.append(entry.path)

    walk(root, 1)
    return all_files, all_dirs


def build_plan(root, max_depth):
    root = os.path.abspath(root)
    all_files, all_dirs = scan(root, max_depth)

    tv_moves = []
    file_renames = []
    tv_claimed_dirs = set()

    for file_path in all_files:
        name = os.path.basename(file_path)
        stem, lang, ext = split_ext_lang(name)
        tv = parse_tv(stem, find_dir_show_hint(file_path))
        if tv:
            base_dir, existing_dir = find_tv_base_dir(file_path, norm_key(tv["show"]))
            show_folder = compute_show_folder_name(existing_dir, tv["show"], tv["year"])
            # Use the canonical folder name (not this file's own casing) so every
            # episode of a show ends up with an identical show-name prefix even if
            # different release batches capitalized it differently.
            show_name = TRAILING_YEAR_PAREN_RE.sub("", show_folder)
            if tv["season"] is not None:
                season_folder = f"Season {tv['season']}"
                code = f"S{tv['season']:02d}E{tv['episode']}"
            else:
                season_folder = None
                code = f"E{tv['episode']}"
            new_filename = (
                f"{show_name} - {tv['title']} - {code}{lang}{ext}"
                if tv["title"]
                else f"{show_name} - {code}{lang}{ext}"
            )
            target = (
                os.path.join(base_dir, show_folder, season_folder, new_filename)
                if season_folder
                else os.path.join(base_dir, show_folder, new_filename)
            )
            if os.path.abspath(target) != os.path.abspath(file_path):
                tv_moves.append((file_path, target))

            d = os.path.dirname(file_path)
            while True:
                tv_claimed_dirs.add(d)
                parent = os.path.dirname(d)
                if os.path.abspath(d) == root or parent == d:
                    break
                d = parent
        else:
            new_name = clean_filename(name)
            if new_name != name:
                file_renames.append((file_path, os.path.join(os.path.dirname(file_path), new_name)))

    dir_renames = []
    for d in sorted(all_dirs, key=lambda p: -p.count(os.sep)):
        if d in tv_claimed_dirs:
            continue
        name = os.path.basename(d)
        if SEASON_DIR_RE.match(name):
            continue
        new_name = clean_dirname(name)
        if new_name != name:
            dir_renames.append((d, os.path.join(os.path.dirname(d), new_name)))

    return file_renames, dir_renames, tv_moves, tv_claimed_dirs


def do_rename(old_path, new_path, apply, label):
    if os.path.abspath(old_path) == os.path.abspath(new_path):
        return
    if os.path.exists(new_path):
        # On a case-insensitive filesystem, a case-only rename (e.g. "of the"
        # -> "Of The") makes os.path.exists(new_path) find old_path itself -
        # not a real conflict.
        same_file = os.path.exists(old_path) and os.path.samefile(old_path, new_path)
        if not same_file:
            print(f"CONFLICT (target exists), skipping: {label}")
            return
    print(label)
    if apply:
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        os.rename(old_path, new_path)


def main():
    parser = argparse.ArgumentParser(description="Simplify movie/TV filenames and organize TV into season folders.")
    parser.add_argument("path", nargs="?", default=".", help="Directory to process (default: cwd)")
    parser.add_argument("-f", "--apply", action="store_true", help="Actually rename/move (default is dry-run)")
    parser.add_argument("--depth", type=int, default=3, help="How many levels deep to recurse (default: 3)")
    args = parser.parse_args()

    if not os.path.isdir(args.path):
        print(f"Not a directory: {args.path}", file=sys.stderr)
        sys.exit(1)

    root = os.path.abspath(args.path)
    file_renames, dir_renames, tv_moves, tv_claimed_dirs = build_plan(root, args.depth)

    total = len(file_renames) + len(dir_renames) + len(tv_moves)
    if not total:
        print("Nothing to do.")
        return

    def rel(p):
        return os.path.relpath(p, os.path.dirname(root))

    for old_path, new_path in file_renames:
        do_rename(old_path, new_path, args.apply, f"{os.path.basename(old_path)}  ->  {os.path.basename(new_path)}")

    for old_path, new_path in dir_renames:
        do_rename(old_path, new_path, args.apply, f"{os.path.basename(old_path)}/  ->  {os.path.basename(new_path)}/")

    for old_path, new_path in tv_moves:
        do_rename(old_path, new_path, args.apply, f"{rel(old_path)}  ->  {rel(new_path)}")

    if args.apply:
        for d in sorted(tv_claimed_dirs, key=lambda p: -p.count(os.sep)):
            try:
                # .DS_Store/._* are harmless macOS metadata caches that regenerate
                # on their own - clear them so a truly-empty folder can be removed.
                for leftover in os.scandir(d):
                    if leftover.name == ".DS_Store" or leftover.name.startswith("._"):
                        os.remove(leftover.path)
            except OSError:
                pass
            try:
                os.rmdir(d)
            except OSError:
                pass
    else:
        print(f"\nDry run: {total} change(s) planned. Re-run with -f/--apply to do it.")


if __name__ == "__main__":
    main()
