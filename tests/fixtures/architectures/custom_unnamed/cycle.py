from gauge import Gauge, ration
from works import Basin, Sluice


def cycle(surge, quota):
    sluice = Sluice(3)
    basin = Basin()
    gauge = Gauge()
    flow = sluice.admit(surge)
    level = basin.settle(flow)
    reading = gauge.read(level)
    return ration(reading, quota)
