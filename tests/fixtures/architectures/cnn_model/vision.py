import torch.nn as nn


class TinyVision(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 16, 3, 1, 1)
        self.pool = nn.MaxPool2d(2)
        self.conv2 = nn.Conv2d(16, 32, 3, 1, 1)
        self.flatten = nn.Flatten()
        self.head = nn.Linear(2048, 10)

    def forward(self, images):
        edges = self.conv1(images)
        small = self.pool(edges)
        shapes = self.conv2(small)
        flat = self.flatten(shapes)
        return self.head(flat)
