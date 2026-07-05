"""PDF label printing onto Avery A4 die-cut sheets. Print at 100 % scale, never
"fit to page".

Two label kinds:

- **ID labels** (25.4 x 10 mm, "25x10-R", 189/sheet): the ID's Data Matrix left, the
  human-readable ID split over two lines (``AGB-`` / ``00305``) right.
- **GHS container labels** (60 x 30 mm, "60x30-R", 24/sheet): item name, signal word,
  H/P statements, hazard pictograms bottom-left, Data Matrix + ID bottom-right.

Both sheet geometries were measured from Avery's calibration sheets
(``sample_data/Avery_*_Kalibrierungsbogen.pdf``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO

from ppf.datamatrix import DataMatrix
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from svglib.svglib import svg2rlg


@dataclass(frozen=True)
class SheetSpec:
    """Geometry of one label stock; all lengths in mm on an A4 page."""

    columns: int
    rows: int
    label_width: float
    label_height: float
    pitch_x: float  # left edge of one column to the next
    pitch_y: float  # top edge of one row to the next
    margin_left: float
    margin_top: float

    @property
    def per_page(self) -> int:
        return self.columns * self.rows


AVERY_25X10_R = SheetSpec(
    columns=7,
    rows=27,
    label_width=25.4,
    label_height=10.0,
    pitch_x=27.94,
    pitch_y=10.0,
    margin_left=8.48,
    margin_top=13.5,
)

AVERY_60X30_R = SheetSpec(
    columns=3,
    rows=8,
    label_width=60.0,
    label_height=30.0,
    pitch_x=65.0,
    pitch_y=35.0,
    margin_left=10.0,
    margin_top=11.0,
)

_FONT = "Helvetica-Bold"
_MAX_FONT_SIZE = 9.0
_PAD = 1.3 * mm  # inset from the label edge; doubles as the matrix quiet zone
_TEXT_GAP = 1.6 * mm  # between the matrix and the text block


_SVG_FIXED_SIZE = re.compile(r'height="(\d+)px" width="(\d+)px"')


def datamatrix_svg(code: str) -> str:
    """Inline SVG of ``code``'s Data Matrix that scales to its container.

    ppf.datamatrix emits a fixed pixel size (one px per module, incl. quiet zone)
    and no viewBox; swap that for a viewBox so CSS controls the rendered size.
    """
    svg = DataMatrix(code).svg()
    svg = svg.removeprefix('<?xml version="1.0" encoding="utf-8" ?>')
    return _SVG_FIXED_SIZE.sub(
        lambda m: (
            f'viewBox="0 0 {m.group(2)} {m.group(1)}" width="100%" height="100%" '
            'shape-rendering="crispEdges"'
        ),
        svg,
        count=1,
    )


def render_label_sheet(
    codes: Sequence[str],
    start_row: int = 1,
    start_column: int = 1,
    spec: SheetSpec = AVERY_25X10_R,
) -> bytes:
    """Render one label per code onto A4 label-sheet PDF pages.

    ``start_row``/``start_column`` (1-based) skip the already-used positions of a
    partially used first sheet; any follow-up sheets start at the top left.
    """
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    canvas.setTitle(f"LabButler labels {codes[0]} – {codes[-1]}" if codes else "LabButler labels")
    position = (start_row - 1) * spec.columns + (start_column - 1)
    for code in codes:
        if position >= spec.per_page:
            canvas.showPage()
            position = 0
        row, column = divmod(position, spec.columns)
        left = (spec.margin_left + column * spec.pitch_x) * mm
        bottom = A4[1] - (spec.margin_top + row * spec.pitch_y + spec.label_height) * mm
        _draw_label(canvas, code, left, bottom, spec)
        position += 1
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _draw_label(canvas: Canvas, code: str, left: float, bottom: float, spec: SheetSpec) -> None:
    """One label: Data Matrix on the left, the ID split at the hyphen on the right."""
    label_width = spec.label_width * mm
    label_height = spec.label_height * mm
    matrix_size = label_height - 2 * _PAD
    _draw_matrix(canvas, DataMatrix(code).matrix, left + _PAD, bottom + _PAD, matrix_size)

    prefix, hyphen, number = code.partition("-")
    lines = [prefix + hyphen, number] if hyphen else [code]
    text_left = left + _PAD + matrix_size + _TEXT_GAP
    text_width = left + label_width - _PAD - text_left
    font_size = _fitting_font_size(lines, text_width)
    leading = font_size * 1.2
    # Baselines chosen so the optical middle of the line block (a line's middle sits
    # roughly 0.36 em above its baseline) lands on the label's vertical center.
    baseline = bottom + label_height / 2 + (len(lines) - 1) / 2 * leading - 0.36 * font_size
    canvas.setFont(_FONT, font_size)
    for line in lines:
        canvas.drawCentredString(text_left + text_width / 2, baseline, line)
        baseline -= leading


def _draw_matrix(
    canvas: Canvas, matrix: list[list[int]], left: float, bottom: float, size: float
) -> None:
    """Draw an ECC200 matrix (rows top-down) as filled squares within ``size`` points."""
    module = size / len(matrix)
    canvas.setFillColorRGB(0, 0, 0)
    for row_from_top, row in enumerate(matrix):
        y = bottom + (len(matrix) - 1 - row_from_top) * module
        for column, bit in enumerate(row):
            if bit:
                canvas.rect(left + column * module, y, module, module, stroke=0, fill=1)


def _fitting_font_size(lines: Sequence[str], max_width: float) -> float:
    """The largest size up to ``_MAX_FONT_SIZE`` at which every line fits ``max_width``."""
    widest = max(stringWidth(line, _FONT, _MAX_FONT_SIZE) for line in lines)
    if widest <= max_width:
        return _MAX_FONT_SIZE
    return _MAX_FONT_SIZE * max_width / widest


# --- GHS container labels (60 x 30 mm) --------------------------------------------------

_GHS_PAD = 1.6 * mm
_BOTTOM_ZONE = 10.0 * mm  # pictogram row (left) and Data Matrix + ID (right)
_PICTOGRAM_SIZE = 9.5 * mm
_GHS_MATRIX_SIZE = 7.5 * mm
_NAME_SIZES = (9.0, 8.0, 7.0, 6.0)
_STATEMENT_SIZES = (5.0, 4.5, 4.0, 3.6, 3.2)
_STATEMENT_FONT = "Helvetica"


@dataclass(frozen=True)
class GhsLabel:
    """Everything one GHS container label shows; plain data so callers stay in charge
    of the ORM/staticfiles lookups and this module stays Django-free."""

    code: str  # the frozen human ID, also encoded in the Data Matrix
    name: str
    signal_word: str = ""  # already display-ready, e.g. "Danger"
    statements: Sequence[str] = field(default_factory=tuple)  # "H225: Highly flammable …"
    pictogram_paths: Sequence[str] = field(default_factory=tuple)  # SVG files, GHS01…GHS09


def render_ghs_label_sheet(
    ghs_labels: Sequence[GhsLabel],
    start_row: int = 1,
    start_column: int = 1,
    spec: SheetSpec = AVERY_60X30_R,
) -> bytes:
    """Render GHS container labels onto A4 label-sheet PDF pages (cf. render_label_sheet)."""
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    canvas.setTitle("LabButler GHS labels")
    position = (start_row - 1) * spec.columns + (start_column - 1)
    for ghs_label in ghs_labels:
        if position >= spec.per_page:
            canvas.showPage()
            position = 0
        row, column = divmod(position, spec.columns)
        left = (spec.margin_left + column * spec.pitch_x) * mm
        bottom = A4[1] - (spec.margin_top + row * spec.pitch_y + spec.label_height) * mm
        _draw_ghs_label(canvas, ghs_label, left, bottom, spec)
        position += 1
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _draw_ghs_label(
    canvas: Canvas, ghs_label: GhsLabel, left: float, bottom: float, spec: SheetSpec
) -> None:
    width = spec.label_width * mm
    height = spec.label_height * mm
    text_width = width - 2 * _GHS_PAD
    cursor = bottom + height - _GHS_PAD  # top of the not-yet-used area, moving down

    # Name: as large as fits on one line, else wrapped/shrunk (max two lines).
    name_size, name_lines = _fit_text_block(
        ghs_label.name, "Helvetica-Bold", text_width, 2 * _NAME_SIZES[0] * 1.2, _NAME_SIZES
    )
    canvas.setFont("Helvetica-Bold", name_size)
    for line in name_lines:
        cursor -= name_size
        canvas.drawString(left + _GHS_PAD, cursor, line)
        cursor -= name_size * 0.2

    if ghs_label.signal_word:
        cursor -= 5.5
        canvas.setFont("Helvetica-Bold", 5.5)
        canvas.drawString(left + _GHS_PAD, cursor, ghs_label.signal_word.upper())
        cursor -= 2

    # H/P statements flow as one wrapped block; the font shrinks to fit and, past the
    # smallest readable size, the tail is cut with an ellipsis (codes lead, so the
    # essential part survives).
    if ghs_label.statements:
        block_height = cursor - (bottom + _BOTTOM_ZONE)
        size, lines = _fit_text_block(
            " ".join(ghs_label.statements),
            _STATEMENT_FONT,
            text_width,
            block_height,
            _STATEMENT_SIZES,
        )
        canvas.setFont(_STATEMENT_FONT, size)
        for line in lines:
            cursor -= size
            canvas.drawString(left + _GHS_PAD, cursor, line)
            cursor -= size * 0.18

    if ghs_label.pictogram_paths:
        # The row must stop short of the Data Matrix zone; with many pictograms
        # (worst case all relevant GHS codes) they shrink rather than collide.
        gap = 0.8 * mm
        row_width = width - 2 * _GHS_PAD - _GHS_MATRIX_SIZE - 2 * mm
        count = len(ghs_label.pictogram_paths)
        size = min(_PICTOGRAM_SIZE, (row_width - (count - 1) * gap) / count)
        for index, path in enumerate(ghs_label.pictogram_paths):
            _draw_pictogram(
                canvas, path, left + _GHS_PAD + index * (size + gap), bottom + _GHS_PAD, size
            )

    # Data Matrix with the ID beneath it, bottom right.
    matrix_left = left + width - _GHS_PAD - _GHS_MATRIX_SIZE
    matrix_bottom = bottom + _GHS_PAD + 2.2 * mm
    _draw_matrix(
        canvas, DataMatrix(ghs_label.code).matrix, matrix_left, matrix_bottom, _GHS_MATRIX_SIZE
    )
    id_size = _fitting_font_size([ghs_label.code], _GHS_MATRIX_SIZE + 2 * mm)
    id_size = min(id_size, 5.0)
    canvas.setFont(_FONT, id_size)
    canvas.drawCentredString(
        matrix_left + _GHS_MATRIX_SIZE / 2, bottom + _GHS_PAD + 0.4 * mm, ghs_label.code
    )


@lru_cache(maxsize=16)
def _pictogram_drawing(path: str):
    return svg2rlg(path)


def _draw_pictogram(canvas: Canvas, path: str, left: float, bottom: float, size: float) -> None:
    drawing = _pictogram_drawing(path)
    # Scale via the canvas transform so the cached drawing is never mutated.
    canvas.saveState()
    canvas.translate(left, bottom)
    scale = size / max(drawing.width, drawing.height)
    canvas.scale(scale, scale)
    renderPDF.draw(drawing, canvas, 0, 0)
    canvas.restoreState()


def _wrap_words(text: str, font: str, size: float, max_width: float) -> list[str]:
    """Greedy word wrap; a word longer than the line keeps its own (overflowing) line."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if not current or stringWidth(trial, font, size) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_text_block(
    text: str, font: str, max_width: float, max_height: float, sizes: Sequence[float]
) -> tuple[float, list[str]]:
    """Wrap ``text``, trying ``sizes`` largest-first, until the block fits ``max_height``.

    If even the smallest size overflows, the block is cut to the lines that fit and the
    last kept line ends in an ellipsis.
    """
    for size in sizes:
        lines = _wrap_words(text, font, size, max_width)
        if len(lines) * size * 1.2 <= max_height:
            return size, lines
    size = sizes[-1]
    lines = _wrap_words(text, font, size, max_width)
    keep = max(1, int(max_height / (size * 1.2)))
    lines = lines[:keep]
    last = lines[-1] + "…"
    while len(last) > 1 and stringWidth(last, font, size) > max_width:
        last = last[:-2] + "…"
    lines[-1] = last
    return size, lines
