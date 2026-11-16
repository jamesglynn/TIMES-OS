# SPDX-License-Identifier: GPL-3.0-or-later
"""The package times-os as a user meets it: installed by pip in a fresh environment, run from an empty folder.

    python .github/scripts/check_package.py <empty work folder> [--python <the environment's python>] [--expected <expected.json>]
                                            [--clean] [--read-only]

With the environment's Python (default: this one): `times-os --version`, `times-os example demo`, `times-os run demo`
(the first run sets the package up), `times-os check`, a second run, `times-os run .` from inside the run folder (the
results in the same place, <work>/times-os-runs/demo, named on the run's last line), `python -m times_os --version`, and with --clean
`times-os clean --yes`. Passes when both runs give DemoS_012's published objective (expected.json, to 1e-9) with the
verdict SAME or SAME OBJECTIVE and its Veda result files, the second run does not set up again, and nothing was
written in the environment's package folders (site-packages before and after: same files, same sizes and times).
--read-only: the package's own folder is made read-only before the runs (and writable again after).
Writes <work>/package_check.json (the times of each step, the setup's steps timed from the first run's console lines,
and the size of the data folder), and copies setup.log and julia_packages.log of the environment's part of the data
folder into <work>.
Exit status 1 otherwise."""
import glob, json, os, re, shutil, stat, subprocess, sys, time
os.environ["TIMES_SETTINGS_FILES"] = "0"      # the runs started here read no times-os.toml: a stray one cannot change a check

work = os.path.abspath(sys.argv[1])
arg = lambda name, default=None: sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default
py = arg("--python", sys.executable)
here = os.path.dirname(os.path.abspath(__file__))
want = json.load(open(arg("--expected", os.path.join(here, "..", "..", "models", "DemoS_012", "expected.json")), encoding="utf-8"))
scripts = os.path.dirname(py)
exe = os.path.join(scripts, "times-os.exe" if os.name == "nt" else "times-os")
bad, steps = [], {}
# the setup's lines on the console: its steps, their ends, the sign of life once a minute
SETUP_LINE = re.compile(r"\s*(\d\. |done|\.\.\. |Setup |The package sets itself up|FAILED)")


def where(code):
    return subprocess.run([py, "-c", code], capture_output=True, text=True, check=True).stdout.strip()


site = json.loads(where("import json, site, sysconfig; print(json.dumps(sorted(set(site.getsitepackages() + [sysconfig.get_paths()['purelib']]))))"))
pkg = where("import os, times_os; print(os.path.dirname(times_os.__file__))")
data = where("from times_os.__main__ import data_folder; print(data_folder())")


def listing():
    out = {}
    for base in site:
        for d, _, files in os.walk(base):
            for f in files:
                p = os.path.join(d, f)
                try:
                    st = os.stat(p)
                    out[p] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    pass
    return out


def run(name, cmd, expect=0, cwd=None):
    t0 = time.time()
    # (as a user's Python: compiled files are written, PYTHONDONTWRITEBYTECODE is not passed on)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    p = subprocess.Popen(cmd, cwd=cwd or work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", env=env)
    lines = []
    for line in p.stdout:              # each line with the seconds since the step began (the setup's steps, timed)
        lines.append((round(time.time() - t0, 1), line.rstrip("\n")))
    p.wait()
    steps[name] = {"seconds": round(time.time() - t0, 1), "exit": p.returncode}
    setup = [f"{t:7.1f} s  {l.strip()}" for t, l in lines if SETUP_LINE.match(l)]
    if setup:
        steps[name]["setup"] = setup
    out = "\n".join(l for _, l in lines)
    print(f"--- {name}: exit {p.returncode}, {steps[name]['seconds']} s\n" + "".join(l + "\n" for l in setup)
          + out[-3000:], flush=True)
    if p.returncode != expect:
        bad.append(f"{name}: exit {p.returncode}")
    return out


def set_read_only(on):
    for d, dirs, files in os.walk(pkg):
        for f in files + dirs:
            p = os.path.join(d, f)
            m = os.stat(p).st_mode
            os.chmod(p, (m & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)) if on else (m | stat.S_IWUSR))


def result(name):
    rep = os.path.join(work, "times-os-runs", "demo", "report_demo.json")
    if not os.path.isfile(rep):
        bad.append(f"{name}: no report"); return
    r = json.load(open(rep, encoding="utf-8"))
    obj, verdict = (r.get("julia") or {}).get("objective"), (r.get("verdict") or "").split(":")[0]
    ok = obj is not None and abs(obj - want["objective"]) <= 1e-9 * abs(want["objective"]) and verdict in ("SAME", "SAME OBJECTIVE")
    lost = [e for e in (".vd", ".vde", ".vds") if not os.path.isfile(os.path.join(work, "times-os-runs", "demo", "demos_012_julia" + e))]
    steps[name].update(objective=obj, verdict=r.get("verdict"), veda_missing=lost)
    print(f"    {name}: {r.get('verdict')}; objective {obj!r} (published {want['objective']!r})" + (f"; missing {lost}" if lost else ""))
    if not ok or lost:
        bad.append(f"{name}: {r.get('verdict')}, objective {obj}, missing {lost}")


os.makedirs(work, exist_ok=True)
if os.listdir(work):
    sys.exit(f"{work} is not empty")
before = listing()
if "--read-only" in sys.argv:
    set_read_only(True)
try:
    out = run("version", [exe, "--version"])
    run("example", [exe, "example", "demo"])
    out = run("first run", [exe, "run", "demo"])
    result("first run")
    if "sets itself up first" not in out:
        bad.append("first run: no line saying that the package sets itself up")
    run("check", [exe, "check"])
    out = run("second run", [exe, "run", "demo"])
    result("second run")
    if "sets itself up" in out or "setup is" in out:
        bad.append("second run: set up again")
    # from inside the run folder: the results go to the same place, beside it (times-os-runs in the folder that holds it)
    out = run("run from inside the run folder", [exe, "run", "."], cwd=os.path.join(work, "demo"))
    result("run from inside the run folder")
    last = [l for l in out.splitlines() if l.strip()][-1:] or [""]
    if last[0] != "Output files available here: " + os.path.join(work, "times-os-runs", "demo"):
        bad.append(f"run from inside the run folder: its last line is {last[0]!r}")
    m = run("python -m times_os", [py, "-m", "times_os", "--version"])
finally:
    if "--read-only" in sys.argv:
        set_read_only(False)
after = listing()
changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
if changed:
    bad.append(f"{len(changed)} files written or changed in site-packages, e.g. {changed[:5]}")
size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(data) for f in fs) if os.path.isdir(data) else 0
res = {"python": py, "package": pkg, "data_folder": data, "data_folder_mb": round(size / 2**20, 1), "steps": steps,
       "site_packages_changed": changed[:50], "failures": bad}
for part in sorted(glob.glob(os.path.join(data, "env-*"))):    # kept beside package_check.json: clean removes the data folder
    for log in ("setup.log", "julia_packages.log"):            # (one part: one environment ran here)
        if os.path.isfile(os.path.join(part, log)):
            shutil.copyfile(os.path.join(part, log), os.path.join(work, log))
if "--clean" in sys.argv:
    run("clean", [exe, "clean", "--yes"])
    if os.path.exists(data):
        bad.append(f"clean: {data} is still there")
json.dump(res, open(os.path.join(work, "package_check.json"), "w"), indent=1)
print(f"\ndata folder {data}: {res['data_folder_mb']} MB after the runs")
print("PASS" if not bad else "FAIL:\n  " + "\n  ".join(bad))
sys.exit(1 if bad else 0)
