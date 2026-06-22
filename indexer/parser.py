"""Parse Navidrome album titles into (date, source_tag, venue) tuples.

Album title convention in the user's library:
    YYYY-MM-DD [(source-quality)] Venue, City, ST

Examples:
    1985-06-22 (sbd 79356) Uptown Lounge, Athens, GA
    2011-01-04 Zebra Bar, Jam Cruise, US
    1974-03-XX (sbd 96895) Fantasy Studios, Berkeley, CA   <- skipped (partial date)
    Billy Plays the Dead                                    <- skipped (no date)
"""

import re

# Strict date regex — refuses YYYY-MM-XX and similar partials.
_TITLE_RE = re.compile(
    r"""
    ^\s*
    (?P<date>\d{4}-\d{2}-\d{2})    # full date
    \s*
    (?:\((?P<source>[^)]+)\)\s*)?  # optional (source-quality)
    (?P<venue>.*?)\s*$             # rest is venue/city/state
    """,
    re.VERBOSE,
)

_LEADING_PUNCT_RE = re.compile(r"^[\s,;:\-–—.]+")


def parse_album_title(title):
    """Return (date, source_tag, venue) or None if not a parseable live show.

    date     -- 'YYYY-MM-DD' string, validated for plausible month/day
    source   -- contents of (parens) or None
    venue    -- cleaned remainder; may be empty string
    """
    if not title:
        return None
    m = _TITLE_RE.match(title)
    if not m:
        return None
    date = m.group("date")
    y, mo, d = int(date[:4]), int(date[5:7]), int(date[8:10])
    if not (1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return None
    source = m.group("source")
    if source is not None:
        source = source.strip() or None
    venue = _LEADING_PUNCT_RE.sub("", m.group("venue")).strip()
    return date, source, venue


if __name__ == "__main__":
    cases = [
        ("1985-06-22 (sbd 79356) Uptown Lounge, Athens, GA",
         ("1985-06-22", "sbd 79356", "Uptown Lounge, Athens, GA")),
        ("2011-01-04 Zebra Bar, Jam Cruise, US",
         ("2011-01-04", None, "Zebra Bar, Jam Cruise, US")),
        ("1966-02-12 (sbd 9514) Watts Acid Test, Youth Opportunities Center, Compton, CA",
         ("1966-02-12", "sbd 9514", "Watts Acid Test, Youth Opportunities Center, Compton, CA")),
        ("1977-12-06 (sbd Miller 174904) The Dome, C.W. Post College, Brookville, NY",
         ("1977-12-06", "sbd Miller 174904", "The Dome, C.W. Post College, Brookville, NY")),
        ("1974-03-XX (sbd 96895) Fantasy Studios, Berkeley, CA", None),
        ("Billy Plays the Dead", None),
        ("", None),
        ("1975-09-18 (aud Miller 17219) Sophie's, Palo Alto, CA",
         ("1975-09-18", "aud Miller 17219", "Sophie's, Palo Alto, CA")),
    ]
    fails = 0
    for title, expected in cases:
        got = parse_album_title(title)
        ok = got == expected
        mark = "OK" if ok else "FAIL"
        print(f"  {mark}  {title!r}")
        if not ok:
            print(f"        expected={expected}")
            print(f"        got     ={got}")
            fails += 1
    print(f"\n{len(cases) - fails}/{len(cases)} parser cases passed")
    raise SystemExit(1 if fails else 0)
