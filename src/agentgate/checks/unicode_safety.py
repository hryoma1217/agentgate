"""unicode_safety.py -- Unicode safety check (AG-BIDI, AG-INVIS, AG-HOMO).

Rules:
  AG-BIDI  (high, always): bidi control characters U+202A-U+202E, U+2066-U+2069.
           Essentially no legitimate use in source files; Trojan-Source vector.
  AG-INVIS (high, code-context only): zero-width and invisible chars
           U+200B, U+2060, U+FEFF (when not BOM at offset 0), U+00AD.
           Only flagged when the file is treated as code AND the char sits
           inside an identifier/string run.
           U+200C/U+200D (ZWNJ/ZWJ) and U+200E/U+200F (LRM/RLM) are NOT
           in AG-INVIS by default -- legitimate in Arabic/Persian/Indic text
           and emoji ZWJ sequences.
           strict_zerowidth=true: adds ZWNJ/ZWJ only inside ASCII-identifier runs.
  AG-HOMO  (medium, opt-in): Latin-looking Cyrillic/Greek codepoints inside
           an otherwise-ASCII identifier.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from ..model import WriteEvent, Issue
    from ..config import GateConfig

from ..model import Issue

# ---------------------------------------------------------------------------
# Bidi control characters
# ---------------------------------------------------------------------------

# U+202A LEFT-TO-RIGHT EMBEDDING
# U+202B RIGHT-TO-LEFT EMBEDDING
# U+202C POP DIRECTIONAL FORMATTING
# U+202D LEFT-TO-RIGHT OVERRIDE
# U+202E RIGHT-TO-LEFT OVERRIDE
# U+2066 LEFT-TO-RIGHT ISOLATE
# U+2067 RIGHT-TO-LEFT ISOLATE
# U+2068 FIRST STRONG ISOLATE
# U+2069 POP DIRECTIONAL ISOLATE
_BIDI_CONTROLS = frozenset(range(0x202A, 0x202F)) | frozenset(range(0x2066, 0x206A))

_BIDI_NAMES = {
    0x202A: "LEFT-TO-RIGHT EMBEDDING",
    0x202B: "RIGHT-TO-LEFT EMBEDDING",
    0x202C: "POP DIRECTIONAL FORMATTING",
    0x202D: "LEFT-TO-RIGHT OVERRIDE",
    0x202E: "RIGHT-TO-LEFT OVERRIDE",
    0x2066: "LEFT-TO-RIGHT ISOLATE",
    0x2067: "RIGHT-TO-LEFT ISOLATE",
    0x2068: "FIRST STRONG ISOLATE",
    0x2069: "POP DIRECTIONAL ISOLATE",
}

# ---------------------------------------------------------------------------
# Invisible characters flagged in code context
# ---------------------------------------------------------------------------

# U+200B ZERO WIDTH SPACE
# U+2060 WORD JOINER
# U+FEFF ZERO WIDTH NO-BREAK SPACE (BOM when at offset 0, else stray)
# U+00AD SOFT HYPHEN
_INVIS_CODE = frozenset([0x200B, 0x2060, 0xFEFF, 0x00AD])

_INVIS_NAMES = {
    0x200B: "ZERO WIDTH SPACE",
    0x2060: "WORD JOINER",
    0xFEFF: "ZERO WIDTH NO-BREAK SPACE (stray BOM)",
    0x00AD: "SOFT HYPHEN",
    0x200C: "ZERO WIDTH NON-JOINER",
    0x200D: "ZERO WIDTH JOINER",
}

# Optional strict_zerowidth additions (ZWNJ/ZWJ in ASCII-identifier context)
_STRICT_ZEROWIDTH = frozenset([0x200C, 0x200D])

# ---------------------------------------------------------------------------
# Homoglyph: Cyrillic and Greek codepoints that look Latin
# ---------------------------------------------------------------------------

# Cyrillic letters that visually resemble ASCII Latin
_CYRILLIC_HOMO = frozenset([
    0x0430,  # а (looks like a)
    0x0435,  # е (looks like e)
    0x043E,  # о (looks like o)
    0x0440,  # р (looks like p)
    0x0441,  # с (looks like c)
    0x0445,  # х (looks like x)
    0x0410,  # А (looks like A)
    0x0412,  # В (looks like B)
    0x0415,  # Е (looks like E)
    0x041A,  # К (looks like K)
    0x041C,  # М (looks like M)
    0x041D,  # Н (looks like H)
    0x041E,  # О (looks like O)
    0x0420,  # Р (looks like P)
    0x0421,  # С (looks like C)
    0x0422,  # Т (looks like T)
    0x0425,  # Х (looks like X)
    0x0443,  # у (looks like y)
])

# Greek letters that visually resemble ASCII Latin
_GREEK_HOMO = frozenset([
    0x03B1,  # α (looks like a)
    0x03B5,  # ε (looks like e)
    0x03B9,  # ι (looks like i)
    0x03BD,  # ν (looks like v)
    0x03BF,  # ο (looks like o)
    0x03C1,  # ρ (looks like p)
    0x03C5,  # υ (looks like u)
    0x0391,  # Α (looks like A)
    0x0392,  # Β (looks like B)
    0x0395,  # Ε (looks like E)
    0x0396,  # Ζ (looks like Z)
    0x0397,  # Η (looks like H)
    0x0399,  # Ι (looks like I)
    0x039A,  # Κ (looks like K)
    0x039C,  # Μ (looks like M)
    0x039D,  # Ν (looks like N)
    0x039F,  # Ο (looks like O)
    0x03A1,  # Ρ (looks like P)
    0x03A4,  # Τ (looks like T)
    0x03A5,  # Υ (looks like Y)
    0x03A7,  # Χ (looks like X)
])

_ALL_HOMO = _CYRILLIC_HOMO | _GREEK_HOMO

# ---------------------------------------------------------------------------
# File profile detection
# ---------------------------------------------------------------------------

def _is_code_profile(file_path: str, code_extensions: list) -> bool:
    """Return True if the file should be treated as source code."""
    if not file_path or file_path in ("<stdin>", ""):
        return False  # unknown -> doc profile (permissive)
    lower = file_path.lower()
    for ext in code_extensions:
        if lower.endswith(ext):
            return True
    return False


# ---------------------------------------------------------------------------
# Context detection: is a character inside an identifier/string run?
# ---------------------------------------------------------------------------

# An identifier/string run: ASCII letters, digits, _, quotes, common code chars
_IDENT_CHARS = re.compile(r'[\w"\'`]')

def _in_identifier_or_string(line: str, col0: int) -> bool:
    """Check if position col0 (0-indexed) is within an identifier or string token."""
    if col0 <= 0 or col0 >= len(line):
        return False
    # Check chars before and after
    before = line[col0 - 1] if col0 > 0 else " "
    after = line[col0 + 1] if col0 + 1 < len(line) else " "
    return bool(_IDENT_CHARS.match(before) or _IDENT_CHARS.match(after))


def _in_ascii_identifier(line: str, col0: int) -> bool:
    """Check if position is within an ASCII-only identifier run."""
    if col0 <= 0 or col0 >= len(line):
        return False
    # Walk back to find start of identifier run
    start = col0
    while start > 0 and (line[start - 1].isascii() and (line[start - 1].isalnum() or line[start - 1] in "_")):
        start -= 1
    # Walk forward to find end
    end = col0
    while end + 1 < len(line) and (line[end + 1].isascii() and (line[end + 1].isalnum() or line[end + 1] in "_")):
        end += 1
    # Valid ASCII identifier must have at least one char before/after
    prefix = line[start:col0]
    suffix = line[col0 + 1:end + 1]
    return bool(prefix or suffix)


# ---------------------------------------------------------------------------
# Main check function
# ---------------------------------------------------------------------------

def run(event: "WriteEvent", cfg: "GateConfig") -> List["Issue"]:
    """Run Unicode safety checks on a WriteEvent. Returns list of Issues."""
    issues: List[Issue] = []
    content = event.content
    if not content:
        return issues

    is_code = _is_code_profile(event.file_path, cfg.unicode.code_extensions)
    lines = content.splitlines()

    # Track absolute character offset to detect BOM at offset 0
    abs_offset = 0

    for line_no, line in enumerate(lines, start=1):
        for col0, ch in enumerate(line):
            cp = ord(ch)
            col1 = col0 + 1  # 1-based column

            # --- AG-BIDI: always flagged regardless of profile ---
            if cp in _BIDI_CONTROLS:
                name = _BIDI_NAMES.get(cp, unicodedata.name(ch, f"U+{cp:04X}"))
                issues.append(Issue(
                    check="unicode",
                    rule_id="AG-BIDI",
                    severity="high",
                    line=line_no,
                    col=col1,
                    message=f"U+{cp:04X} {name}",
                    excerpt=repr(ch),
                    suggestion="Remove the bidi control char; it visually reorders source.",
                ))
                abs_offset += 1
                continue

            # --- AG-INVIS: code profile only, inside identifier/string run ---
            if is_code and cp in _INVIS_CODE:
                # Special case: FEFF at absolute offset 0 is a BOM (benign)
                if cp == 0xFEFF and abs_offset == 0 and line_no == 1 and col0 == 0:
                    abs_offset += 1
                    continue
                if _in_identifier_or_string(line, col0):
                    name = _INVIS_NAMES.get(cp, unicodedata.name(ch, f"U+{cp:04X}"))
                    issues.append(Issue(
                        check="unicode",
                        rule_id="AG-INVIS",
                        severity="high",
                        line=line_no,
                        col=col1,
                        message=f"U+{cp:04X} {name} inside identifier/string",
                        excerpt=repr(ch),
                        suggestion="Remove the invisible character; it can hide malicious code.",
                    ))

            # --- AG-INVIS strict_zerowidth: ZWNJ/ZWJ in ASCII-identifier runs ---
            elif is_code and cfg.unicode.strict_zerowidth and cp in _STRICT_ZEROWIDTH:
                if _in_ascii_identifier(line, col0):
                    name = _INVIS_NAMES.get(cp, unicodedata.name(ch, f"U+{cp:04X}"))
                    issues.append(Issue(
                        check="unicode",
                        rule_id="AG-INVIS",
                        severity="high",
                        line=line_no,
                        col=col1,
                        message=f"U+{cp:04X} {name} inside ASCII identifier (strict_zerowidth)",
                        excerpt=repr(ch),
                        suggestion="Remove ZWNJ/ZWJ from ASCII identifier; use only in appropriate script contexts.",
                    ))

            # --- AG-HOMO: opt-in, medium severity ---
            if cfg.unicode.homoglyph and cp in _ALL_HOMO:
                # Only flag if the surrounding identifier is otherwise ASCII
                if _in_ascii_identifier(line, col0):
                    try:
                        name = unicodedata.name(ch, f"U+{cp:04X}")
                    except Exception:
                        name = f"U+{cp:04X}"
                    issues.append(Issue(
                        check="unicode",
                        rule_id="AG-HOMO",
                        severity="medium",
                        line=line_no,
                        col=col1,
                        message=f"U+{cp:04X} {name} looks like ASCII but is Cyrillic/Greek",
                        excerpt=repr(ch),
                        suggestion="Replace with the visually identical ASCII character.",
                    ))

            abs_offset += 1
        # Account for newline character
        abs_offset += 1

    return issues
