class Sluice:
    def __init__(self, width):
        self.width = width

    def admit(self, surge):
        return min(surge, self.width)


class Basin:
    def settle(self, flow):
        return flow * 0.5
