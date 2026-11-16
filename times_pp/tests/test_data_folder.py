# SPDX-License-Identifier: GPL-3.0-or-later
"""The data folder of the installed package (times-os): only a folder of its own is written in or removed, and one
setup at a time is made in it.

  python -m pytest times_pp/tests/test_data_folder.py

No Julia and no model are needed: the launcher (times_os) is started from this repository, as `pip install -e .`
does, with TIMES_DATA set to a temporary folder; the setup lock is tried on each runner (TIMES.py, and public/TIMES.py
where there is one).
"""
import importlib.util, json, os, subprocess, sys, time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNNERS = [p for p in ("TIMES.py", os.path.join("public", "TIMES.py")) if os.path.isfile(os.path.join(ROOT, p))]
MARKER = "times-os-data.txt"


def times_os(data, *args):
    env = dict(os.environ, TIMES_DATA=str(data), PYTHONPATH=ROOT, TIMES_UPDATE_CHECK="0")
    p = subprocess.run([sys.executable, "-m", "times_os", *args], cwd=str(data.parent), env=env,
                       capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


@pytest.mark.parametrize("command", [["run", "demo"], ["check"], ["setup"], ["verify", "x"], ["clean", "--yes"]])
def test_a_folder_of_other_things_is_never_used(tmp_path, command):
    data = tmp_path / "data"
    data.mkdir()
    (data / "mine.txt").write_text("keep")
    code, out = times_os(data, *command)
    assert code == 2
    assert "is not a data folder that times-os made" in out and MARKER in out
    assert sorted(os.listdir(data)) == ["mine.txt"] and (data / "mine.txt").read_text() == "keep"


def test_version_writes_nothing(tmp_path):
    data = tmp_path / "data"
    code, out = times_os(data, "--version")
    assert code == 0 and out.startswith("times-os ")
    assert not data.exists()


def test_a_marked_folder_is_cleaned(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / MARKER).write_text("times-os")
    (data / "settings.json").write_text("{}")
    code, out = times_os(data, "clean", "--yes")
    assert code == 0, out
    assert not data.exists()


def test_a_new_folder_is_marked(tmp_path):
    sys.path.insert(0, ROOT)
    try:
        from times_os.__main__ import adopt
    finally:
        sys.path.remove(ROOT)
    data = tmp_path / "new"
    assert adopt(str(data)) and (data / MARKER).is_file()
    (tmp_path / "empty").mkdir()
    assert adopt(str(tmp_path / "empty")) and (tmp_path / "empty" / MARKER).is_file()
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "x").write_text("x")
    assert not adopt(str(tmp_path / "full")) and not (tmp_path / "full" / MARKER).exists()


def load(rel):
    name = "runner_" + rel.replace(os.sep, "_").replace(".", "_")
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


@pytest.fixture(params=RUNNERS)
def T(request, tmp_path):
    mod = load(request.param)
    saved = mod.STATE
    mod.STATE = str(tmp_path)
    yield mod
    mod.STATE = saved


def gone_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_a_lock_of_a_process_that_is_gone_is_taken_over(T, tmp_path, capsys):
    lock = tmp_path / "setup.lock"
    lock.write_text(json.dumps({"pid": gone_pid(), "started": "2026-01-01T00:00:00"}))
    got = T.setup_lock()
    assert got == str(lock)
    assert json.loads(lock.read_text())["pid"] == os.getpid()
    assert "left behind" in capsys.readouterr().out
    T.setup_unlock(got)
    assert not lock.exists() and os.listdir(tmp_path) == []


def test_an_old_lock_is_taken_over(T, tmp_path):
    lock = tmp_path / "setup.lock"
    lock.write_text(json.dumps({"pid": os.getppid(), "started": "2026-01-01T00:00:00"}))     # a live process
    old = time.time() - T.LOCK_STALE - 60
    os.utime(lock, (old, old))
    got = T.setup_lock()
    assert json.loads(lock.read_text())["pid"] == os.getpid()
    T.setup_unlock(got)
    assert not lock.exists()


def test_a_lock_is_given_back_only_by_its_own_process(T, tmp_path):
    lock = tmp_path / "setup.lock"
    lock.write_text(json.dumps({"pid": os.getppid(), "started": "now"}))
    T.setup_unlock(str(lock))
    assert lock.exists()


def test_a_live_lock_is_waited_for_and_a_finished_setup_is_not_made_again(T, tmp_path, capsys):
    lock = tmp_path / "setup.lock"
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])
    try:
        lock.write_text(json.dumps({"pid": holder.pid, "started": "now"}))
        import threading
        threading.Timer(3, lambda: lock.unlink()).start()          # the other setup ends
        t0 = time.time()
        got = T.setup_lock(done=lambda: True)                      # ... and was what this one needed
        assert got is None and time.time() - t0 >= 2.5
        assert "this one waits for it" in capsys.readouterr().out
        assert not lock.exists()
    finally:
        holder.wait()


# --- installed: where the results go without --out ---------------------------------------------------------------

def run_folder(where, name="Demo", run=None):
    """A run folder: a run file and a DD file. -> its path"""
    d = os.path.join(str(where), name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, (run or name) + ".run"), "w") as f:
        f.write("$BATINCLUDE base.dd\n")
    with open(os.path.join(d, "base.dd"), "w") as f:
        f.write("SET X / A /;\n")
    return d


@pytest.fixture
def installed(T, monkeypatch):
    monkeypatch.setattr(T, "INSTALLED", {"version": "0.0.0"})
    monkeypatch.setattr(T, "RUN_DEFAULT", None)
    return T


def go(T, monkeypatch, capsys, args, cwd=None):
    """run <args>, installed, with the work of each case stubbed. -> (exit status, {case: its result root}, last line)"""
    ran = {}

    def one_case(c, out_root, o, name):
        ran[name] = out_root
        return {"case": name, "verdict": "SOLVED", "checks": [], "timings": {}}

    monkeypatch.setattr(T, "one_case", one_case)
    monkeypatch.setattr(T, "refresh_workload", lambda: None)
    monkeypatch.setattr(T, "compile_notice", lambda j: None)
    monkeypatch.setattr(T, "find_julia", lambda *a: None)
    monkeypatch.setattr(T, "write", lambda *a: None)
    if cwd:
        monkeypatch.chdir(cwd)
    capsys.readouterr()
    code = T.run([str(a) for a in args])
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    return code, ran, lines[-1] if lines else ""


def test_one_case_from_inside_its_parent_and_elsewhere_the_same_place(installed, monkeypatch, capsys, tmp_path):
    d = run_folder(tmp_path / "models")
    want = os.path.join(str(tmp_path / "models"), "times-os-runs")
    (tmp_path / "elsewhere").mkdir()
    for args, cwd in ((["."], d), ([os.path.join("models", "Demo")], tmp_path / ""), (["Demo"], tmp_path / "models"),
                      ([d], tmp_path / "elsewhere"), ([os.path.join(d, "Demo.run")], tmp_path / "elsewhere")):
        installed.RUN_DEFAULT = None
        code, ran, last = go(installed, monkeypatch, capsys, args, cwd)
        assert code == 0 and ran == {"Demo": want}, (args, cwd, ran)
        assert last == f"Output files available here: {os.path.join(want, 'Demo')}"


def test_two_sibling_cases_one_place_in_their_parent(installed, monkeypatch, capsys, tmp_path):
    a, b = run_folder(tmp_path / "models", "A"), run_folder(tmp_path / "models", "B")
    code, ran, last = go(installed, monkeypatch, capsys, [a, b])
    want = os.path.join(str(tmp_path / "models"), "times-os-runs")
    assert code == 0 and ran == {"A": want, "B": want}
    assert last == f"Output files available here: {want}"


def test_two_cases_at_different_depths_beside_the_higher_one(installed, monkeypatch, capsys, tmp_path):
    a, b = run_folder(tmp_path / "models", "A"), run_folder(tmp_path / "models" / "more" / "deep", "B")
    code, ran, _ = go(installed, monkeypatch, capsys, [a, b])
    want = os.path.join(str(tmp_path / "models"), "times-os-runs")
    assert code == 0 and ran == {"A": want, "B": want}


def test_out_overrides(installed, monkeypatch, capsys, tmp_path):
    d = run_folder(tmp_path / "models")
    code, ran, last = go(installed, monkeypatch, capsys, [d, "--out", tmp_path / "res"])
    assert code == 0 and ran == {"Demo": str(tmp_path / "res")}
    assert last == f"Output files available here: {os.path.join(str(tmp_path / 'res'), 'Demo')}"


def test_with_out_nothing_is_made_or_tried_beside_the_model(installed, monkeypatch, capsys, tmp_path):
    d = run_folder(tmp_path / "models")
    import tempfile
    tried = []
    monkeypatch.setattr(tempfile, "TemporaryFile", lambda *a, **k: tried.append(k.get("dir")) or open(os.devnull, "w"))
    made = []
    real = os.mkdir
    monkeypatch.setattr(installed.os, "mkdir", lambda p, *a: made.append(p) or real(p, *a))
    code, ran, _ = go(installed, monkeypatch, capsys, [d, "--out", tmp_path / "res"])
    beside = os.path.join(str(tmp_path / "models"), "times-os-runs")
    assert code == 0 and beside not in made and beside not in tried and not os.path.exists(beside)
    assert installed.RUN_DEFAULT == beside       # still named (TIMESPP_RESULTS), not tried


def test_a_place_that_cannot_be_written_stops_before_any_work(installed, monkeypatch, capsys, tmp_path):
    d = run_folder(tmp_path / "models")
    import tempfile

    def refuse(*a, **k):
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(tempfile, "TemporaryFile", refuse)
    code, ran, last = go(installed, monkeypatch, capsys, [d])
    assert code == 2 and ran == {}
    assert "Give --out" in last and "cannot be written" in last


def under_a_drive(T, monkeypatch, can_make):
    """installed_out for C:\\MyCase (/MyCase), with the drive's answers stubbed: times-os-runs can be made there or not.
    -> (out, why, [the folders made], [the folders removed])"""
    import tempfile
    root = os.path.abspath(os.sep)
    want = os.path.join(root, "times-os-runs")
    made, removed = [], []

    def mkdir(p, *a):
        if not can_make:
            raise PermissionError(13, "Access is denied")
        made.append(p)
    monkeypatch.setattr(os.path, "isdir", lambda p: p in made)
    monkeypatch.setattr(os, "mkdir", mkdir)
    monkeypatch.setattr(os, "rmdir", lambda p: removed.append(p))
    monkeypatch.setattr(tempfile, "TemporaryFile", lambda **k: open(os.devnull, "w"))
    out, why = T.installed_out([os.path.join(root, "MyCase")])
    monkeypatch.undo()
    assert out == want
    return out, why, made, removed


def test_a_run_folder_directly_under_a_drive_where_times_os_runs_can_be_made(installed, monkeypatch):
    out, why, made, removed = under_a_drive(installed, monkeypatch, True)
    assert why is None and made == [out] and removed == [out]      # tried, and not left behind


def test_a_run_folder_directly_under_a_drive_where_it_cannot_be_made(installed, monkeypatch):
    out, why, made, removed = under_a_drive(installed, monkeypatch, False)
    assert why and "cannot be made" in why and made == [] and removed == []


@pytest.mark.skipif(os.name != "nt", reason="drives are Windows's")
def test_run_folders_on_different_drives_go_beside_the_first(installed):
    out, why = installed.installed_out([r"E:\models\A", r"C:\other\B"])
    assert out == r"E:\models\times-os-runs"


def test_a_times_os_runs_folder_of_other_things_is_not_replaced(installed, monkeypatch, capsys, tmp_path):
    d = run_folder(tmp_path / "models")
    other = tmp_path / "models" / "times-os-runs" / "Demo"
    other.mkdir(parents=True)
    (other / "mine.txt").write_text("keep")
    code, ran, _ = go(installed, monkeypatch, capsys, [d])
    assert code == 2 and ran == {} and (other / "mine.txt").read_text() == "keep"


# --- the settings file of run (times-os.toml) --------------------------------------------------------------------

def test_every_option_of_the_parser_is_a_key(T):
    """The settings file's keys are the parser's options: each `--name` that run() reads has its line in RUN_OPTIONS."""
    import inspect, re
    src = inspect.getsource(T.run)
    parsed = set(re.findall(r'a == "--([a-z0-9-]+)"', src)) | {n[2:] for g in re.findall(r'a in \(([^)]*)\)', src)
                                                                for n in re.findall(r'"(--[a-z0-9-]+)"', g)}
    parsed -= {"no-matrix"}                     # an option that is gone: the parser says so
    assert parsed == set(T.RUN_OPTIONS), (parsed - set(T.RUN_OPTIONS), set(T.RUN_OPTIONS) - parsed)


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("USERPROFILE", str(h))
    monkeypatch.setenv("HOME", str(h))
    for k in ("TIMES_POINTS", "TIMES_GAMS", "TIMES_SETTINGS_FILES"):
        monkeypatch.delenv(k, raising=False)
    return h


def settle(T, monkeypatch, capsys, args):
    """run <args> with each case stubbed. -> (exit status, {case: (out_root, its options)}, the output)"""
    ran = {}

    def one_case(c, out_root, o, name):
        ran[name] = (out_root, dict(o))
        return {"case": name, "verdict": "SOLVED", "checks": [], "timings": {}}

    monkeypatch.setattr(T, "one_case", one_case)
    monkeypatch.setattr(T, "refresh_workload", lambda: None)
    monkeypatch.setattr(T, "compile_notice", lambda j: None)
    monkeypatch.setattr(T, "find_julia", lambda *a: None)
    monkeypatch.setattr(T, "write", lambda *a: None)
    capsys.readouterr()
    code = T.run([str(a) for a in args])
    return code, ran, capsys.readouterr().out


def test_no_settings_file_nothing_changes(T, monkeypatch, capsys, tmp_path, home):
    d = run_folder(tmp_path / "models")
    code, ran, out = settle(T, monkeypatch, capsys, [d, "--out", tmp_path / "res"])
    assert code == 0 and ran["Demo"][1]["threads"] == 0 and "Settings files" not in out
    assert T.RUN_FILES == []


def test_a_file_beside_the_run_folders_parent_and_a_relative_out(T, monkeypatch, capsys, tmp_path, home):
    d = run_folder(tmp_path / "models" / "group")
    (tmp_path / "models" / "times-os.toml").write_text('threads = 6\nout = "results"\nsolver-option = ["a=1", "b=2"]\n')
    code, ran, out = settle(T, monkeypatch, capsys, [d])
    assert code == 0
    root, o = ran["Demo"]
    assert o["threads"] == 6 and o["solver_options"] == ["a=1", "b=2"]
    assert root == os.path.join(str(tmp_path / "models"), "results")      # relative to the file's folder
    assert f"Settings files read: {tmp_path / 'models' / 'times-os.toml'}" in out


def test_the_users_own_file(T, monkeypatch, capsys, tmp_path, home):
    d = run_folder(tmp_path / "models")
    (home / "times-os.toml").write_text("threads = 3\nkeep = true\n")
    code, ran, out = settle(T, monkeypatch, capsys, [d, "--out", tmp_path / "res"])
    assert code == 0 and ran["Demo"][1]["threads"] == 3 and ran["Demo"][1]["keep"] is True
    assert str(home / "times-os.toml") in out


def test_the_nearest_file_wins_over_the_users_and_the_command_line_over_both(T, monkeypatch, capsys, tmp_path, home):
    d = run_folder(tmp_path / "models")
    (home / "times-os.toml").write_text("threads = 3\ntolerance = 1e-5\n")
    (tmp_path / "times-os.toml").write_text("threads = 5\n")
    code, ran, out = settle(T, monkeypatch, capsys, [d, "--out", tmp_path / "res"])
    assert ran["Demo"][1]["threads"] == 5 and ran["Demo"][1]["tolerance"] == 1e-5
    code, ran, out = settle(T, monkeypatch, capsys, [d, "--out", tmp_path / "res", "--threads", "9", "--tolerance", "1e-7"])
    assert ran["Demo"][1]["threads"] == 9 and ran["Demo"][1]["tolerance"] == 1e-7


def test_an_unknown_key_stops_before_any_work(T, monkeypatch, capsys, tmp_path, home):
    d = run_folder(tmp_path / "models")
    (tmp_path / "models" / "times-os.toml").write_text("thread = 4\n")
    code, ran, out = settle(T, monkeypatch, capsys, [d, "--out", tmp_path / "res"])
    assert code == 2 and ran == {}
    assert "times-os.toml: thread is not an option of run" in out and "Nothing was run" in out


@pytest.mark.parametrize("line", ['threads = "8"', "keep = 1", 'solver-option = "a=1"', "time-limit = true"])
def test_a_wrong_value_stops_before_any_work(T, monkeypatch, capsys, tmp_path, home, line):
    d = run_folder(tmp_path / "models")
    (tmp_path / "models" / "times-os.toml").write_text(line + "\n")
    code, ran, out = settle(T, monkeypatch, capsys, [d, "--out", tmp_path / "res"])
    assert code == 2 and ran == {}
    assert f"times-os.toml: {line.split(' =')[0]} = " in out and "is not" in out


def test_config_says_where_each_value_comes_from(T, monkeypatch, capsys, tmp_path, home):
    d = run_folder(tmp_path / "models")
    (home / "times-os.toml").write_text("threads = 3\n")
    (tmp_path / "models" / "times-os.toml").write_text("keep = true\n")
    monkeypatch.setenv("TIMES_GAMS", r"C:\GAMS\gams.exe")
    capsys.readouterr()
    assert T.config([d]) == 0
    out = capsys.readouterr().out
    line = lambda k: next(l for l in out.splitlines() if l.strip().startswith(k + " "))
    assert str(home / "times-os.toml") in line("threads") and "3" in line("threads")
    assert str(tmp_path / "models" / "times-os.toml") in line("keep")
    assert "environment (TIMES_GAMS)" in line("gams-exe")
    assert "(default)" in line("solver")


def test_settings_files_off(T, monkeypatch, capsys, tmp_path, home):
    d = run_folder(tmp_path / "models")
    (home / "times-os.toml").write_text("threads = 3\n")
    (tmp_path / "models" / "times-os.toml").write_text("keep = true\n")
    monkeypatch.setenv("TIMES_SETTINGS_FILES", "0")
    code, ran, out = settle(T, monkeypatch, capsys, [d, "--out", tmp_path / "res"])
    assert code == 0 and ran["Demo"][1]["threads"] == 0 and ran["Demo"][1]["keep"] is False
    assert "Settings files" not in out and T.RUN_FILES == []
    assert T.config([d]) == 0
    out = capsys.readouterr().out
    assert "TIMES_SETTINGS_FILES=0" in out and "none found" in out and "not there" in out


def test_cases_is_given_on_the_command_line_only(T, monkeypatch, capsys, tmp_path, home):
    d = run_folder(tmp_path / "models")
    run_folder(tmp_path / "other", "Extra")
    (tmp_path / "models" / "times-os.toml").write_text(f'cases = ["{(tmp_path / "other").as_posix()}"]\n')
    code, ran, out = settle(T, monkeypatch, capsys, [d, "--out", tmp_path / "res"])
    assert code == 2 and ran == {}
    assert "cases is given on the command line only" in out


@pytest.mark.parametrize("key, case, value", [("jacobian", "Demo", True), ("check", "after", "after"),
                                              ("profile", "cpu", "cpu")])
def test_a_switch_of_a_file_never_takes_a_word_of_the_command_line(T, monkeypatch, capsys, tmp_path, home, key, case, value):
    """jacobian, check and profile take a value when the next word fits; from a file (true) they never take the first
    word of the command line: here a case named by its run file without .run, or a case whose name is such a value."""
    d = run_folder(tmp_path / "models", case)
    for f in ("expected.json", "gams_matrix.db3"):          # check: a GAMS result is there (no GAMS is needed)
        open(os.path.join(d, f), "w").close()
    (tmp_path / "models" / "times-os.toml").write_text(f"{key} = true\n")
    monkeypatch.chdir(tmp_path / "models")
    first = os.path.join(case, case) if key == "jacobian" else case        # jacobian: models/Demo/Demo (no .run)
    code, ran, out = settle(T, monkeypatch, capsys, [first, "--out", tmp_path / "res"])
    assert code == 0 and list(ran) == [case], out
    assert ran[case][1][key] == value


def test_each_environment_has_its_own_part_and_shares_the_rest(T, monkeypatch, tmp_path):
    """Installed: settings, the Julia environment, the precompile workload and the Segment Heap copy go to a part of
    the data folder named by the Python and the place of the code; Julia that setup installs, the TIMES source and
    the setup lock stay at the top, shared."""
    for name in ("PROG", "INSTALLED", "STATE", "PART", "SETTINGS", "JULIA_ENV", "VENV", "JULIA_BIN", "SEGHEAP",
                 "WORKLOAD_DIR", "WORKLOAD_TXT", "WORKLOAD_JSON"):
        monkeypatch.setattr(T, name, getattr(T, name))
    for k in ("TIMESEQ_WORKLOAD", "TIMESPP_KERNELS_PROJECT", "TIMESPP_JULIA_BINDIR"):
        monkeypatch.delenv(k, raising=False)
    data = str(tmp_path / "data")
    os.makedirs(data)                                          # (the launcher makes it and marks it)
    parts = []
    for prefix in (str(tmp_path / "venvA"), str(tmp_path / "venvB"), str(tmp_path / "venvA")):
        monkeypatch.setattr(sys, "prefix", prefix)
        T.launched("times-os", "0.0.0", data)
        parts.append(T.PART)
        assert os.path.dirname(T.PART) == data and os.path.basename(T.PART).startswith("env-")
        for p in (T.SETTINGS, T.JULIA_ENV, T.SEGHEAP, T.WORKLOAD_DIR):
            assert os.path.dirname(p) == T.PART
        assert T.JULIA_BIN == os.path.join(data, ".julia_bin")
        assert os.environ["TIMESPP_KERNELS_PROJECT"] == T.JULIA_ENV
    assert parts[0] != parts[1] and parts[0] == parts[2]       # A, B, A: two parts, the first one found again
    got = T.setup_lock()
    assert got == os.path.join(data, "setup.lock")             # one lock for the whole data folder
    T.setup_unlock(got)


def test_a_julia_older_than_1_11_is_passed_by(T, monkeypatch, tmp_path):
    """setup's find_julia(check=True) passes by a Julia older than 1.11 (the one saved, or on the PATH) and takes the
    next one, here a portable copy in .julia_bin; check names the old one MISSING; find_julia() unchecked is as before."""
    exe = "julia.exe" if os.name == "nt" else "julia"
    old = tmp_path / "old" / "bin" / exe
    new = tmp_path / "jb" / "julia-1.13.1" / "bin" / exe
    for f in (old, new):
        f.parent.mkdir(parents=True)
        f.write_text("")
    versions = {str(old): "julia version 1.10.0", str(new): "julia version 1.13.1"}
    monkeypatch.setattr(T, "call", lambda cmd, **k: (0, versions.get(os.path.abspath(cmd[0]), ""), 0.1))
    monkeypatch.setattr(T, "settings", lambda: {})
    monkeypatch.setattr(T.shutil, "which", lambda name: str(old) if name == "julia" else None)
    monkeypatch.setattr(T.os.path, "expanduser", lambda p: str(tmp_path / "home"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setattr(T, "JULIA_BIN", str(tmp_path / "jb"))
    assert T.find_julia() == str(old)
    assert T.find_julia(check=True) == str(new)
    assert T.JULIA_OLD == [(str(old), "julia version 1.10.0")]
    assert T.find_julia(str(old), check=True) == str(new) and len(T.JULIA_OLD) == 1     # given and on the PATH: once


def test_a_run_with_a_julia_older_than_1_11_says_so_and_asks_its_version_once(T, monkeypatch, tmp_path, capsys):
    """A Julia saved by an earlier setup and older than 1.11: the run's note names both versions and goes on; the
    version is asked once and kept in settings.json beside that Julia, and asked again for another Julia."""
    old, new = str(tmp_path / "old" / "julia.exe"), str(tmp_path / "new" / "julia.exe")
    asked = []
    versions = {old: "julia version 1.10.0", new: "julia version 1.13.1"}

    def call(cmd, **k):
        asked.append(cmd[0])
        return 0, versions[cmd[0]], 0.1
    monkeypatch.setattr(T, "call", call)
    monkeypatch.setattr(T, "SETTINGS", str(tmp_path / "settings.json"))
    T.old_julia_notice(old)
    T.old_julia_notice(old)
    out = capsys.readouterr().out
    assert out.count("the Julia in use is 1.10.0") == 2 and "needs Julia 1.11 or newer" in out and "goes on" in out
    assert asked == [old]
    assert T.settings()["julia_version"]["version"] == "1.10.0"
    T.old_julia_notice(new)
    assert capsys.readouterr().out == "" and asked == [old, new]
    assert T.settings()["julia_version"]["version"] == "1.13.1"


def test_the_julia_step_stopped_at_its_limit_is_not_a_failure_when_the_packages_are_installed(T, monkeypatch, tmp_path):
    """setup's Julia packages step: done; stopped at its 2-hour limit (exit None) with TimesEq, JuMP and HiGHS in the
    Manifest: the line says so and that the rest is compiled when a run needs it; FAILED for an error, and for a stop
    without the packages."""
    env = tmp_path / ".julia_env"
    env.mkdir()
    monkeypatch.setattr(T, "JULIA_ENV", str(env))
    assert not T.julia_packages_installed()
    (env / "Manifest.toml").write_text("[[deps.JuMP]]\n\n[[deps.HiGHS]]\n")
    assert not T.julia_packages_installed()
    (env / "Manifest.toml").write_text("[[deps.HiGHS]]\nuuid = \"x\"\n\n[[deps.JuMP]]\n\n[[deps.TimesEq]]\npath = \"t\"\n")
    assert T.julia_packages_installed()
    assert T.julia_step_line(0, "", True) == "done"
    stopped = T.julia_step_line(None, "Precompiling TimesEqStochastic", True)
    assert stopped.startswith("stopped after 2 hours") and "when a run needs it" in stopped and "FAILED" not in stopped
    assert T.julia_step_line(None, "Precompiling", False).startswith("FAILED:")
    failed = T.julia_step_line(1, "ERROR: LoadError: x", True)
    assert failed.startswith("FAILED:") and "ERROR: LoadError: x" in failed
    # what follows the step (the paths pinned, julia_bindir for the kernels) is done after a finished step and after
    # a stop with the packages installed, not after a failure
    assert [T.julia_step_ok(c, i) for c, i in ((0, True), (0, False), (None, True), (None, False), (1, True))] == \
        [True, True, True, False, False]


def test_installed_with_pip_is_said_a_beta_by_version_check_and_the_first_setup_only(installed, monkeypatch, capsys, tmp_path):
    """The beta line: in --version and check installed, and before the first setup (not before one made again for an
    update); not in a run, and not in a checkout's --version."""
    T = installed
    beta = "Installed with pip: a beta feature; tell us what you find:"
    assert beta in T.version_text()
    monkeypatch.setattr(T, "INSTALLED", None)
    monkeypatch.setattr(T, "revision", lambda: "abc")
    assert beta not in T.version_text()
    monkeypatch.setattr(T, "INSTALLED", {"version": "0.0.0"})
    monkeypatch.setattr(T, "find_julia", lambda *a: None)
    monkeypatch.setattr(T, "call", lambda cmd, **k: (1, "", 0.1))
    T.check()
    assert beta in capsys.readouterr().out
    monkeypatch.setattr(T, "setup_logged", lambda a, quiet=False: 0)
    monkeypatch.setattr(T, "setup_key", lambda: {"version": "0.0.2"})
    for rec, said in (({}, True), ({"version": "0.0.1"}, False)):
        monkeypatch.setattr(T, "settings", lambda: {"installed": rec})
        assert T.setup_first_locked() == 0
        assert (beta in capsys.readouterr().out) == said, rec
    code, ran, last = go(T, monkeypatch, capsys, [run_folder(tmp_path / "models")])
    assert code == 0 and beta not in last


@pytest.fixture
def clone(T, monkeypatch, tmp_path):
    """A checkout's runner with its state in a new folder `clone` (no .venv, no .julia_env, no settings.json), whose
    programs and pip are recorded, not started; run itself is a stub."""
    c = tmp_path / "clone"
    c.mkdir()
    monkeypatch.setattr(T, "INSTALLED", None)
    monkeypatch.setattr(T, "STATE", str(c))
    for name, rel in (("SETTINGS", "settings.json"), ("JULIA_ENV", ".julia_env"), ("VENV", ".venv")):
        monkeypatch.setattr(T, name, str(c / rel))
    monkeypatch.delenv("TIMES_SETUP_CHECK", raising=False)
    started = []
    monkeypatch.setattr(T, "call", lambda cmd, **k: started.append(cmd) or (0, "", 0.0))
    monkeypatch.setattr(T.subprocess, "call", lambda cmd, **k: started.append(cmd) or 0)
    monkeypatch.setattr(T, "reexec_in_venv", lambda: None)
    monkeypatch.setattr(T, "update_check_start", lambda: None)
    monkeypatch.setattr(T, "duckdb_version", lambda exe: "1.5.6")
    monkeypatch.setattr(T, "run", lambda a: started.append(["run"] + a) or 0)
    monkeypatch.setattr(T, "verify", lambda a: started.append(["verify"] + a) or 0)
    T.started = started
    return c


@pytest.mark.parametrize("command", ["run", "verify"])
def test_a_clone_never_set_up_says_so_and_stops(T, clone, capsys, tmp_path, command):
    """No .venv, no .julia_env, no setup in settings.json: one line, exit 2, nothing started (no pip) or written."""
    d = run_folder(tmp_path / "models")
    code = T.main([command, d, "--no-solve", "--check"])
    out = capsys.readouterr().out
    assert code == 2 and "This clone has not been set up: python TIMES.py setup does it, once" in out
    assert len([l for l in out.splitlines() if l.strip()]) == 1
    assert T.started == [] and os.listdir(clone) == []


@pytest.mark.parametrize("old", ["julia_env", "venv", "settings"])
def test_a_clone_with_a_setup_however_old_runs_on(T, clone, capsys, tmp_path, old):
    if old == "julia_env":
        (clone / ".julia_env").mkdir()
    elif old == "venv":
        exe = clone / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
        exe.parent.mkdir(parents=True)
        exe.write_text("")
    else:
        (clone / "settings.json").write_text(json.dumps({"julia": "julia", "setup": "full"}))
    assert T.main(["run", "x"]) == 0 and T.started == [["run", "x"]]
    assert "not been set up" not in capsys.readouterr().out


def test_times_setup_check_0_lets_a_clone_without_setup_run(T, clone, monkeypatch, capsys):
    monkeypatch.setenv("TIMES_SETUP_CHECK", "0")
    assert T.main(["run", "x"]) == 0 and T.started == [["run", "x"]]


@pytest.mark.parametrize("version", ["2.0.0", "2.1.0rc1", None])
@pytest.mark.parametrize("installed", [False, True])
def test_a_duckdb_the_code_cannot_use_is_named_and_the_run_stops(T, clone, monkeypatch, capsys, version, installed):
    """DuckDB 2 or none in the Python that runs the preprocessor (a stand-in for its version): one line naming it,
    the requirement and what puts it right; exit 2 before any work. check names it MISSING."""
    (clone / ".julia_env").mkdir()
    monkeypatch.setattr(T, "duckdb_version", lambda exe: version)
    if installed:
        monkeypatch.setattr(T, "INSTALLED", {"version": "0.0.0"})
        monkeypatch.setattr(T, "setup_first", lambda: T.started.append(["setup"]) or 0)
    assert T.main(["run", "x"]) == 2 and T.started == []
    out = capsys.readouterr().out.strip()
    assert len(out.splitlines()) == 1 and out.endswith("Nothing was run.") and "TIMES-OS needs duckdb<2" in out
    assert (f"DuckDB {version} is in the Python that runs the preprocessor" if version else "DuckDB is not installed") in out
    assert ("pip install --force-reinstall times-os" if installed else "python TIMES.py setup") in out
    line = [l for l in T.check(verbose=False)[2] if l[1].startswith("DuckDB")]
    assert len(line) == 1 and line[0][0] == "MISSING"


def test_a_duckdb_older_than_2_passes_and_check_says_ok(T, clone, capsys):
    (clone / ".julia_env").mkdir()
    assert T.main(["run", "x"]) == 0 and T.started == [["run", "x"]]
    line = [l for l in T.check(verbose=False)[2] if l[1].startswith("DuckDB")]
    assert line[0][0] == "ok" and line[0][2].startswith("1.5.6 (")


def test_the_duckdb_bound_is_the_one_of_requirements_and_pyproject(T):
    req = [l.split("#")[0].strip() for l in open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8")]
    assert T.DUCKDB_REQUIREMENT in req
    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as f:
        assert f'"{T.DUCKDB_REQUIREMENT}",' in f.read()
    assert T.version_tuple("2.0.0") >= T.version_tuple("2") > T.version_tuple("1.5.6.dev3")
