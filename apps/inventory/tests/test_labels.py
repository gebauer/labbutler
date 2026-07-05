"""Tests for the Data Matrix label-sheet PDF renderer (Avery 25.4 x 10 mm stock)."""

import base64
import re
import zlib

from apps.inventory import labels

SPEC = labels.AVERY_25X10_R


def _page_count(pdf: bytes) -> int:
    # Every page object carries "/Type /Page"; subtract the one "/Type /Pages" tree node.
    return pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")


def _decompressed_content(pdf: bytes) -> bytes:
    """Undo reportlab's ASCII85+Flate stream encoding to expose the drawing operators."""
    content = b""
    for stream in re.findall(rb"stream\b(.*?)endstream", pdf, re.S):
        stream = stream.strip(b"\r\n")
        if stream.endswith(b"~>"):  # PDF ASCII85 streams end with '~>' but lack '<~'
            stream = base64.a85decode(b"<~" + stream, adobe=True)
        try:
            content += zlib.decompress(stream)
        except zlib.error:
            content += stream
    return content


def test_spec_grid_fills_a4_exactly():
    # The measured geometry must tile A4 (210 x 297 mm) with symmetric margins —
    # this is what keeps the print aligned with the physical die-cut labels.
    width = 2 * SPEC.margin_left + (SPEC.columns - 1) * SPEC.pitch_x + SPEC.label_width
    height = 2 * SPEC.margin_top + SPEC.rows * SPEC.pitch_y
    assert round(width, 2) == 210.0
    assert round(height, 2) == 297.0
    assert SPEC.per_page == 189


def test_render_is_a_pdf_with_both_text_lines():
    pdf = labels.render_label_sheet(["AGB-00305"])
    assert pdf.startswith(b"%PDF")
    content = _decompressed_content(pdf)
    # The ID is printed human-readably, split at the hyphen into two lines.
    assert b"(AGB-)" in content
    assert b"(00305)" in content


def test_full_sheet_fits_one_page_and_overflows_to_a_second():
    codes = [f"AGB-{n:05d}" for n in range(1, SPEC.per_page + 1)]
    assert _page_count(labels.render_label_sheet(codes)) == 1
    codes.append("AGB-99999")
    assert _page_count(labels.render_label_sheet(codes)) == 2


def test_start_position_offsets_only_the_first_page():
    # Starting at the last label of the sheet leaves room for exactly one label;
    # the second code must flow onto a fresh page.
    pdf = labels.render_label_sheet(
        ["AGB-00001", "AGB-00002"], start_row=SPEC.rows, start_column=SPEC.columns
    )
    assert _page_count(pdf) == 2


def test_legacy_code_without_hyphen_renders_single_line():
    pdf = labels.render_label_sheet(["ch0005"])
    assert b"(ch0005)" in _decompressed_content(pdf)


def test_datamatrix_svg_scales_to_container():
    svg = labels.datamatrix_svg("AGB-00305")
    assert svg.startswith("<svg")  # no XML declaration — meant for inline embedding
    assert 'viewBox="0 0 16 16"' in svg  # 14x14 symbol + 1 module quiet zone
    assert 'width="100%"' in svg
    assert "px" not in svg


def test_ghs_spec_grid_fills_a4_exactly():
    spec = labels.AVERY_60X30_R
    width = 2 * spec.margin_left + (spec.columns - 1) * spec.pitch_x + spec.label_width
    height = 2 * spec.margin_top + (spec.rows - 1) * spec.pitch_y + spec.label_height
    assert round(width, 2) == 210.0
    assert round(height, 2) == 297.0
    assert spec.per_page == 24


def _acetone_label() -> labels.GhsLabel:
    return labels.GhsLabel(
        code="AGB-00305",
        name="Acetone",
        signal_word="Danger",
        statements=[
            "H225: Highly flammable liquid and vapour.",
            "H319: Causes serious eye irritation.",
            "H336: May cause drowsiness or dizziness.",
            "P210: Keep away from heat, hot surfaces, sparks, open flames and other "
            "ignition sources. No smoking.",
        ],
        pictogram_paths=[
            "labbutler/static/img/ghs/GHS02.svg",
            "labbutler/static/img/ghs/GHS07.svg",
        ],
    )


def test_ghs_label_renders_name_statements_and_id():
    pdf = labels.render_ghs_label_sheet([_acetone_label()])
    assert pdf.startswith(b"%PDF")
    content = _decompressed_content(pdf)
    assert b"(Acetone)" in content
    assert b"DANGER" in content
    assert b"H225" in content
    assert b"P210" in content
    assert b"(AGB-00305)" in content
    assert _page_count(pdf) == 1


def test_ghs_label_without_hazards_renders_minimal_label():
    plain = labels.GhsLabel(code="AGB-00001", name="PCR tubes")
    content = _decompressed_content(labels.render_ghs_label_sheet([plain]))
    assert b"(PCR tubes)" in content
    assert b"(AGB-00001)" in content


def test_ghs_label_overlong_statements_are_truncated_not_overflowing():
    monster = labels.GhsLabel(
        code="AGB-00002",
        name="Very nasty compound with an extremely long descriptive chemical name",
        signal_word="Danger",
        statements=[f"H{300 + i}: " + "hazard statement text " * 6 for i in range(12)],
    )
    pdf = labels.render_ghs_label_sheet([monster])
    assert pdf.startswith(b"%PDF")
    assert _page_count(pdf) == 1


def test_ghs_sheet_start_position_and_overflow():
    spec = labels.AVERY_60X30_R
    two = [_acetone_label(), _acetone_label()]
    pdf = labels.render_ghs_label_sheet(two, start_row=spec.rows, start_column=spec.columns)
    assert _page_count(pdf) == 2
