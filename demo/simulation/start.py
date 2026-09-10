"""Start the bundled Gazebo world with its known spawn pose initialized in AMCL."""

import os
import tempfile
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory

base = Path(get_package_share_directory("nav2_bringup")) / "params/nav2_params.yaml"
config = yaml.safe_load(base.read_text())
amcl = config["amcl"]["ros__parameters"]
amcl["set_initial_pose"] = True
amcl["initial_pose"] = {"x": -2.0, "y": -0.5, "z": 0.0, "yaw": 0.0}
with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as file:
    yaml.safe_dump(config, file)
    params = file.name
os.execvp(
    "ros2",
    [
        "ros2",
        "launch",
        "nav2_bringup",
        "tb3_simulation_launch.py",
        "headless:=True",
        "use_rviz:=False",
        f"params_file:={params}",
    ],
)
