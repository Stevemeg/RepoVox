import torch
import torch.nn as nn


class DigitClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 16, 3, 1, 1)
        self.act = nn.ReLU()
        self.pool = nn.MaxPool2d(2)
        self.conv2 = nn.Conv2d(16, 32, 3, 1, 1)
        self.head = nn.Linear(1568, 10)

    def forward(self, images):
        hidden = self.pool(self.act(self.conv1(images)))
        hidden = self.pool(self.act(self.conv2(hidden)))
        return self.head(hidden.flatten(1))


def train(loader, epochs):
    model = DigitClassifier()
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01, momentum=0.9)
    for _ in range(epochs):
        for images, labels in loader:
            logits = model(images)
            loss = criterion(logits, labels)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
    return model
