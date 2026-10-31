"""What an element is made of, as it should read: for whatever shows one."""

from __future__ import annotations

from newswitch.instrument import spec


def facts_of(element: spec.Element) -> dict[str, str]:
    """What an element is made of, as it should read."""
    facts: dict[str, str] = {}
    match element:
        case spec.Source():
            facts["emits"] = element.emits
            facts["wavelength"] = ", ".join(f"{line.center:g} nm" for line in element.spectrum)
            facts["max power"] = f"{element.max_power:g} mW"
        case spec.Lens():
            if element.f is not None:
                facts["focal length"] = f"{element.f:g} mm"
            if element.na is not None:
                facts["NA"] = f"{element.na:g}"
                facts["immersion"] = f"n = {element.index:g}"
            if element.magnification is not None:
                facts["magnification"] = f"{element.magnification:g}x"
            if element.prescription is not None:
                facts["prescription"] = element.prescription
        case spec.Filter(curve=curve) | spec.Dichroic(curve=curve):
            facts["curve"] = "open" if curve is None else curve.type
            for name in ("center", "width", "cut"):
                if hasattr(curve, name):
                    facts[name] = f"{getattr(curve, name):g} nm"
            if hasattr(curve, "peak"):
                facts["peak"] = f"{curve.peak:.0%}"
        case spec.Splitter():
            facts["reflects"] = f"{element.reflect:.0%}"
            facts["transmits"] = f"{element.transmit:.0%}"
        case spec.Sensor():
            facts["pixels"] = f"{element.axes['x'].size} x {element.axes['y'].size}"
            facts["pitch"] = f"{element.axes['x'].pitch:g} um"
            facts["bit depth"] = str(element.readout.bit_depth)
        case spec.PointDetector():
            facts["bit depth"] = str(element.readout.bit_depth)
            for name, axis in element.axes.items():
                facts[name] = f"{axis.size} x {axis.step:g} ps"
        case spec.Scanner():
            facts["steps"] = f"{element.axes['x'].size} x {element.axes['y'].size}"
            facts["per step"] = f"{element.axes['x'].step:g} deg"
        case spec.Pinhole():
            facts["diameter"] = f"{element.diameter:g} um"
    return facts
