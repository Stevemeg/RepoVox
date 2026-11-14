import torch
import torch.nn as nn


class SelfAttention(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.query = nn.Linear(dim, dim)
        self.key = nn.Linear(dim, dim)
        self.value = nn.Linear(dim, dim)
        self.out = nn.Linear(dim, dim)

    def forward(self, x):
        q = self.query(x)
        k = self.key(x)
        v = self.value(x)
        weights = torch.softmax(q @ k.transpose(-2, -1), dim=-1)
        return self.out(weights @ v)


class Block(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.attention = SelfAttention(dim)
        self.norm1 = nn.LayerNorm(dim)
        self.feed = nn.Linear(dim, dim)
        self.norm2 = nn.LayerNorm(dim)

    def forward(self, x):
        attended = self.attention(x)
        mixed = self.norm1(x + attended)
        fed = self.feed(mixed)
        return self.norm2(mixed + fed)


class Encoder(nn.Module):
    def __init__(self, vocab, dim):
        super().__init__()
        self.embed = nn.Embedding(vocab, dim)
        self.block1 = Block(dim)
        self.block2 = Block(dim)
        self.head = nn.Linear(dim, vocab)

    def forward(self, tokens):
        hidden = self.embed(tokens)
        first = self.block1(hidden)
        second = self.block2(first)
        return self.head(second)
