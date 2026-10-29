"""Sanity checks that the reference Lightroom preset has the fields we rely on."""

import xml.etree.ElementTree as ET
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
CRS = "http://ns.adobe.com/camera-raw-settings/1.0/"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"


def _description() -> ET.Element:
    root = ET.parse(FIXTURES / "lr_preset_reference.xmp").getroot()
    desc = root.find(f"{{{RDF}}}RDF/{{{RDF}}}Description")
    assert desc is not None
    return desc


def test_color_grading_fields_present() -> None:
    desc = _description()
    expected = {
        "SplitToningShadowHue": "44",
        "SplitToningShadowSaturation": "4",
        "SplitToningHighlightHue": "59",
        "SplitToningHighlightSaturation": "3",
        "SplitToningBalance": "+82",
        "ColorGradeMidtoneHue": "54",
        "ColorGradeMidtoneSat": "2",
        "ColorGradeShadowLum": "+54",
        "ColorGradeMidtoneLum": "+16",
        "ColorGradeHighlightLum": "+3",
        "ColorGradeBlending": "100",
        "ColorGradeGlobalHue": "0",
        "ColorGradeGlobalSat": "0",
        "ColorGradeGlobalLum": "0",
    }
    for field, value in expected.items():
        assert desc.get(f"{{{CRS}}}{field}") == value, field


def test_tone_curves_present() -> None:
    desc = _description()
    counts = {
        "ToneCurvePV2012": 7,
        "ToneCurvePV2012Red": 3,
        "ToneCurvePV2012Green": 2,
        "ToneCurvePV2012Blue": 2,
    }
    for field, n_points in counts.items():
        points = desc.findall(f"{{{CRS}}}{field}/{{{RDF}}}Seq/{{{RDF}}}li")
        assert len(points) == n_points, field
        for point in points:
            assert point.text is not None
            x, y = (int(v) for v in point.text.split(","))
            assert 0 <= x <= 255 and 0 <= y <= 255
