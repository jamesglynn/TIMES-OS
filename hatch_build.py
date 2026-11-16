# SPDX-License-Identifier: GPL-3.0-or-later
"""The wheel's build hook (hatchling): the runner's tree goes into the wheel as times_os/_tree, for the standard wheel
only. An editable install (pip install -e .) then carries no copy of it: its launcher runs the clone's code."""
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

TREE = ["TIMES.py", "times_pp", "times_eq", "times_rpt", "models/DemoS_012"]


class TreeHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name == "wheel" and version == "standard":
            build_data["force_include"].update({p: f"times_os/_tree/{p}" for p in TREE})
