import torch
from models import Generator

LATENT_DIM = 100


def sample(weights, count):
    generator = Generator()
    generator.load_state_dict(weights)
    generator.eval()
    with torch.no_grad():
        z = torch.randn(count, LATENT_DIM)
        images = generator(z)
    return images
