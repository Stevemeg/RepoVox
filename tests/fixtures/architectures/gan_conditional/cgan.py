import torch
import torch.nn as nn
import torch.nn.functional as F

NZ = 64
CLASSES = 10


class CondGenerator(nn.Module):
    def __init__(self):
        super().__init__()
        self.embed = nn.Embedding(CLASSES, NZ)
        self.up1 = nn.ConvTranspose2d(128, 64, 4, 1, 0)
        self.bn1 = nn.BatchNorm2d(64)
        self.up2 = nn.ConvTranspose2d(64, 1, 4, 2, 1)
        self.out = nn.Tanh()

    def forward(self, z, labels):
        joined = torch.cat([z, self.embed(labels)], dim=1)
        hidden = F.relu(self.bn1(self.up1(joined.view(-1, 128, 1, 1))))
        return self.out(self.up2(hidden))


class CondCritic(nn.Module):
    def __init__(self):
        super().__init__()
        self.embed = nn.Embedding(CLASSES, 64)
        self.conv1 = nn.Conv2d(2, 64, 4, 2, 1)
        self.act = nn.LeakyReLU(0.2)
        self.conv2 = nn.Conv2d(64, 1, 4, 1, 0)

    def forward(self, images, labels):
        plane = self.embed(labels).view(-1, 1, 8, 8)
        return self.conv2(self.act(self.conv1(torch.cat([images, plane], dim=1))))


def fit(loader, steps):
    net_g = CondGenerator()
    net_d = CondCritic()
    optim_g = torch.optim.Adam(net_g.parameters(), lr=0.0001)
    optim_d = torch.optim.Adam(net_d.parameters(), lr=0.0004)
    for _ in range(steps):
        for images, labels in loader:
            noise = torch.randn(images.size(0), NZ)
            generated = net_g(noise, labels)

            score_real = net_d(images, labels)
            score_fake = net_d(generated.detach(), labels)
            d_loss = F.binary_cross_entropy_with_logits(
                score_real, torch.ones_like(score_real)
            ) + F.binary_cross_entropy_with_logits(score_fake, torch.zeros_like(score_fake))
            optim_d.zero_grad()
            d_loss.backward()
            optim_d.step()

            score = net_d(generated, labels)
            g_loss = F.binary_cross_entropy_with_logits(score, torch.ones_like(score))
            optim_g.zero_grad()
            g_loss.backward()
            optim_g.step()
