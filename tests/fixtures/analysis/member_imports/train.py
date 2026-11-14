from models import Discriminator, Generator


def train(batch):
    generator = Generator()
    discriminator = Discriminator()
    return discriminator.score(generator.sample(batch))
