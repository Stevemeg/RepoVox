class Gauge:
    def read(self, level):
        return round(level, 1)


def ration(reading, quota):
    return min(reading, quota)
