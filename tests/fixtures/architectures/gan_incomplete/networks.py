import torch
import torch.nn as nn


class Generator(nn.Module):
    def __init__(self, layers):
        super().__init__()
        self.net = nn.Sequential(*layers)

    def forward(self, z):
        return self.net(z)


class Discriminator(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(784, 1), nn.Sigmoid())

    def forward(self, x):
        return self.net(x)


def train(generator, discriminator, loader, optimizer):
    # The models arrive as parameters: which classes they are is not statically bound.
    for real, _ in loader:
        z = torch.randn(real.size(0), 100)
        fake = generator(z)
        loss = discriminator(fake).mean() - discriminator(real).mean()
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()


def preview():
    generator = Generator([nn.Linear(100, 784)])
    z = torch.randn(4, 100)
    return generator(z)
