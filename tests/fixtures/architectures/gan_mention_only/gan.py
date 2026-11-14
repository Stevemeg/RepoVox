"""GAN utilities: generator and discriminator helpers are planned here."""

import torch

GAN_NAME = "PlannedGAN"


class GANConfig:
    def __init__(self, latent_dim, generator_layers, discriminator_layers):
        self.latent_dim = latent_dim
        self.generator_layers = generator_layers
        self.discriminator_layers = discriminator_layers


def describe_gan(config):
    noise = torch.randn(1, config.latent_dim)
    return {"name": GAN_NAME, "noise_shape": tuple(noise.shape)}
