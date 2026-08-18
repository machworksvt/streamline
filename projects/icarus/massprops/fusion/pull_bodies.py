"""Fusion 360 script: dump every B-Rep body of the active design as one pipe-separated row.

Run inside Fusion (Utilities → Scripts, or through the Fusion MCP `fusion_mcp_execute` script
feature — same `run(context)` entry point). Prints a header row `HDR|...` and one row per body,
walking every occurrence depth-first; body proxies are taken in the ROOT context, so positions
and moments are in the design's root frame (Icarus: X aft, Y right, Z up, origin = OpenVSP
origin; nose tip at X = -822 mm).

Columns (units as Fusion's API reports them):
  path            occurrence path from the root, '/' separated ('/ROOT' for root-level bodies)
  body            body name
  mass_kg, vol_cm3, area_cm2
  cx_cm, cy_cm, cz_cm       centre of mass, root frame
  Ixx..Ixz        kg*cm^2 moments about the ROOT ORIGIN, order xx,yy,zz,xy,yz,xz. TENSOR entries
                  (I_xy = -∫xy dm; verified 2026-08-18 on a lone body far from the origin)
  material, density   material name and its `structural_Density` (kg/m^3; '' if unavailable)
  visible, lightbulb, solid   0/1

Every body is emitted regardless of visibility (Fusion's UI 'Physical' panel counts only visible
bodies, and its root-level low-accuracy path did not reproduce the sum of parts on the Icarus
model — see README.md); the streamline side decides what to include.
"""

import adsk.core
import adsk.fusion


def run(_context):
    app = adsk.core.Application.get()
    des = adsk.fusion.Design.cast(app.activeProduct)
    root = des.rootComponent
    acc = adsk.fusion.CalculationAccuracy.HighCalculationAccuracy
    print("HDR|path|body|mass_kg|vol_cm3|area_cm2|cx_cm|cy_cm|cz_cm|Ixx|Iyy|Izz|Ixy|Iyz|Ixz|"
          "material|density|visible|lightbulb|solid")

    def row(path, b):
        pp = b.getPhysicalProperties(acc)
        c = pp.centerOfMass
        _ok, xx, yy, zz, xy, yz, xz = pp.getXYZMomentsOfInertia()
        mat = b.material.name if b.material else ""
        dens = ""
        try:
            dens = "%.6g" % b.material.materialProperties.itemById("structural_Density").value
        except Exception:  # noqa: BLE001 — a material without a density property
            pass
        cells = [path, b.name, "%.6g" % pp.mass, "%.6g" % pp.volume, "%.6g" % pp.area,
                 "%.5g" % c.x, "%.5g" % c.y, "%.5g" % c.z,
                 "%.6g" % xx, "%.6g" % yy, "%.6g" % zz, "%.6g" % xy, "%.6g" % yz, "%.6g" % xz,
                 mat, dens, str(int(b.isVisible)), str(int(b.isLightBulbOn)), str(int(b.isSolid))]
        print("|".join(str(v).replace("|", "/") for v in cells))

    def walk(occs, path):
        for o in occs:
            p = path + "/" + o.name
            for b in o.bRepBodies:
                row(p, b)
            walk(o.childOccurrences, p)

    for b in root.bRepBodies:
        row("/ROOT", b)
    walk(root.occurrences, "")
