# SPDX-License-Identifier: GPL-3.0-or-later
"""The filter of domain violations (timespp/domfilter.py) on a domain set with no members.

  python tests/test_domfilter.py

DemoS_012 with a blend (BLE TRAGSL, its spec OCT), once with SET SPE / 'OCT' / and once without it. GAMS checks a
label against the declared set even when it is empty: without SPE, 'OCT' violates the domain of BL_TYPE, BL_SPEC,
BL_COM and BL_START (error 170), and the GDX reload of gdxfilter.gms removes those records, so no blend row is built.
With SPE, every record stays. No GAMS is needed. Exit status 0 when all pass.
"""
import os, sys, shutil, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
ROOT = os.path.dirname(os.path.dirname(HERE))
DEMO = os.path.join(ROOT, "models", "DemoS_012")
SRC = os.path.join(os.path.dirname(HERE), "timespp", "times_src")

BLEND = """$ONEMPTY
$ONEPS
$ONWARNING
SET BLE / 'TRAGSL' /;
SET OPR / 'GSL', 'NAP' /;
{spe}
PARAMETER BL_TYPE / 'REG1'.'TRAGSL'.'OCT' 2 /;
PARAMETER BL_SPEC / 'REG1'.'TRAGSL'.'OCT' 90 /;
PARAMETER BL_COM / 'REG1'.'TRAGSL'.'GSL'.'OCT' 95, 'REG1'.'TRAGSL'.'NAP'.'OCT' 70 /;
PARAMETER BL_START / 'REG1'.'TRAGSL'.'OCT' 2020 /;
"""
BLEND_SYMBOLS = {"BL_TYPE": 1, "BL_SPEC": 1, "BL_COM": 2, "BL_START": 1}


def filtered_counts(with_spe):
    from timespp.load import read_case, build_db
    from timespp import controls, sysconst, domfilter
    d = tempfile.mkdtemp(prefix="domfilter_")
    try:
        for f in os.listdir(DEMO):
            if f.endswith((".dd", ".run")):
                shutil.copy(os.path.join(DEMO, f), d)
        open(os.path.join(d, "cov_case.dd"), "w").write(BLEND.format(spe="SET SPE / 'OCT' /;" if with_spe else ""))
        run = os.path.join(d, "demos_012.run")
        text = open(run, newline="").read()
        anchor = "$BATINCLUDE uc_nuc_maxcap.dd"
        assert anchor in text, f"{anchor} not in DemoS_012's run file"
        open(run, "w", newline="").write(text.replace(anchor, anchor + "\n$BATINCLUDE cov_case.dd", 1))
        rd, _ = read_case(run, SRC)
        db = build_db(rd, ":memory:")
        controls.derive(db)
        sysconst.load(db)
        found = domfilter.apply(db)
        return {s: db.card(s) for s in BLEND_SYMBOLS}, found, db.log
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    from timespp.domfilter import QA_LINE
    bad = []
    kept, found, log = filtered_counts(True)
    if kept != BLEND_SYMBOLS or found:
        bad.append(f"with SET SPE: records {kept}, violations {len(found)}; expected {BLEND_SYMBOLS} and none")
    gone, found, log = filtered_counts(False)
    want = {s: 0 for s in BLEND_SYMBOLS}
    if gone != want:
        bad.append(f"without SET SPE: records {gone}; expected none (GAMS removes them: error 170 against empty SPE)")
    if len(found) != sum(BLEND_SYMBOLS.values()) or QA_LINE not in log:
        bad.append(f"without SET SPE: {len(found)} violations listed, the QA line {'in' if QA_LINE in log else 'not in'} "
                   f"the log; expected {sum(BLEND_SYMBOLS.values())} and the line")
    for b in bad:
        print("FAIL " + b)
    print(f"FAIL: {len(bad)}" if bad else "PASS: an empty domain set filters every record under it, as GAMS does")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
