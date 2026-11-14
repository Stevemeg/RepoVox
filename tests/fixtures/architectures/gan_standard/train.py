import torch
import torch.nn as nn
from models import Discriminator, Generator

LATENT_DIM = 100


def train(loader, epochs, device):
    generator = Generator().to(device)
    discriminator = Discriminator().to(device)
    criterion = nn.BCELoss()
    opt_g = torch.optim.Adam(generator.parameters(), lr=0.0002, betas=(0.5, 0.999))
    opt_d = torch.optim.Adam(discriminator.parameters(), lr=0.0002, betas=(0.5, 0.999))
    for _ in range(epochs):
        for real, _ in loader:
            real = real.view(real.size(0), -1).to(device)
            ones = torch.ones(real.size(0), 1, device=device)
            zeros = torch.zeros(real.size(0), 1, device=device)

            z = torch.randn(real.size(0), LATENT_DIM, device=device)
            fake = generator(z)

            opt_d.zero_grad()
            loss_real = criterion(discriminator(real), ones)
            loss_fake = criterion(discriminator(fake.detach()), zeros)
            loss_d = loss_real + loss_fake
            loss_d.backward()
            opt_d.step()

            opt_g.zero_grad()
            loss_g = criterion(discriminator(fake), ones)
            loss_g.backward()
            opt_g.step()
    return generator
