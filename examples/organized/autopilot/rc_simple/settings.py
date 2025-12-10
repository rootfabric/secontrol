
import time
from secontrol.common import close, prepare_grid
from secontrol.devices.remote_control_device import RemoteControlDevice

from secontrol.tools.navigation_tools import goto



if __name__ == "__main__":

    grid = prepare_grid("taburet")

    remote = grid.get_first_device(RemoteControlDevice)



    remote.set_mode("oneway")
    remote.set_collision_avoidance(False)
    remote.gyro_control_off()
    # remote.goto(point_target, speed=speed)


