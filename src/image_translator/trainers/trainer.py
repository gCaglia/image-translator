"""Training module for image translator."""

import json
from pathlib import Path
from typing import List, Literal, Optional, Tuple

import dill
import torch
from torch import nn
from torch.optim import Adam
from torch.utils.data.dataloader import DataLoader

from image_translator.data import datasets
from image_translator.networks import networks
from image_translator.utils.utils import get_logger


class TrainArtifact:
    def __init__(
        self,
        model: nn.Module,
        train_losses: List[float],
        baseline_loss: Optional[float] = None,
        test_loss: Optional[float] = None,
    ) -> None:
        self.model = model
        self.train_losses = train_losses
        self.test_loss = test_loss
        self.baseline_loss = baseline_loss

    def dump_metrics(self, path: Path):
        metrics = {
            "baseline_loss": self.baseline_loss,
            "train_losses": self.train_losses,
            "test_loss": self.test_loss,
        }
        path = Path(path)
        path.parent.mkdir(exist_ok=True, parents=True)

        with path.open("w", encoding="utf-8") as f:
            json.dump(metrics, f)

    def dump_model(self, path: Path):
        path = Path(path)
        path.parent.mkdir(exist_ok=True, parents=True)
        with path.open("wb") as f:
            dill.dump(self.model, f)


class Trainer:

    CRITERION = nn.MSELoss()
    LOG_EVERY = 10
    LOGGER = get_logger("Trainer")

    def __init__(self) -> None:
        self.encoder_blocks = [
            networks.ConvBlock(
                in_channels=3,
                num_hidden_layers=3,
                out_channels=8,
                initializer=nn.MaxPool2d(2),
                padding=1,
            ),
            networks.ConvBlock(
                in_channels=8,
                num_hidden_layers=3,
                out_channels=8,
                initializer=nn.MaxPool2d(2),
                padding=1,
            ),
            networks.ConvBlock(
                in_channels=8,
                num_hidden_layers=3,
                out_channels=8,
                initializer=nn.MaxPool2d(2),
                padding=1,
            ),
            networks.ConvBlock(
                in_channels=8,
                num_hidden_layers=3,
                out_channels=8,
                initializer=nn.MaxPool2d(2),
                padding=1,
            ),
        ]
        self.decoder_blocks = [
            networks.ConvBlock(
                in_channels=8,
                num_hidden_layers=3,
                out_channels=8,
                initializer=nn.UpsamplingNearest2d(scale_factor=2),
                padding=1,
            ),
            networks.ConvBlock(
                in_channels=8,
                num_hidden_layers=3,
                out_channels=8,
                initializer=nn.UpsamplingNearest2d(scale_factor=2),
                padding=1,
            ),
            networks.ConvBlock(
                in_channels=8,
                num_hidden_layers=3,
                out_channels=8,
                initializer=nn.UpsamplingNearest2d(scale_factor=2),
                padding=1,
            ),
            networks.ConvBlock(
                in_channels=8,
                num_hidden_layers=3,
                out_channels=3,
                initializer=nn.UpsamplingNearest2d(scale_factor=2),
                padding=1,
            ),
        ]

    def get_data(
        self, train_size: float = 0.9, batch_size: int = 64
    ) -> Tuple[DataLoader, DataLoader]:
        train_images, test_images = datasets.TrainTestSplitPaths.get_split(
            train_size=train_size
        )
        train_dataset = datasets.ImageDataset(train_images)
        test_dataset = datasets.ImageDataset(test_images)
        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=True)

        return train_loader, test_loader

    def fit(
        self,
        train_loader: DataLoader,
        test_loader: Optional[DataLoader] = None,
        lr: float = 2e-2,
        epochs: int = 10,
        device: Literal["cpu", "cuda"] = "cpu",
    ) -> TrainArtifact:
        encoder = networks.Encoder(
            conv_blocks=self.encoder_blocks, adapter_shape=(8, 16, 16)
        )
        decoder = networks.Decoder(
            conv_blocks=self.decoder_blocks, adapter_shape=(8, 16, 16)
        )
        autoencoder = networks.AutoEncoder(
            encoder=encoder, decoder=decoder, device=device
        )
        if test_loader is not None:
            self.LOGGER.info("Getting baseline_loss...")
            with torch.no_grad():
                baseline_loss = 0.0
                for batch in test_loader:
                    out = autoencoder(batch)
                    baseline_loss += float(self.CRITERION(out, batch.to(device))) / len(
                        batch
                    )

            self.LOGGER.info("Baseline_loss: %s", baseline_loss)
        else:
            baseline_loss = None

        train_losses = []
        optimizer = Adam(lr=lr, params=autoencoder.parameters())
        for epoch in range(1, epochs + 1):
            epoch_loss = 0.0
            for original in train_loader:
                optimizer.zero_grad()
                reconstructed = autoencoder(original)
                batch_loss = self.CRITERION(reconstructed, original.to(device))
                batch_loss.backward()
                optimizer.step()
                epoch_loss += float(batch_loss) / len(original)

            if epoch % self.LOG_EVERY == 0:
                self.LOGGER.info("Epoch %s/%s; loss: %s", epoch, epochs, epoch_loss)
            train_losses.append(epoch_loss)

        if test_loader is not None:
            with torch.no_grad():
                self.LOGGER.info("Getting test_loss...")
                test_loss = 0.0
                for batch in test_loader:
                    out = autoencoder(batch)
                    test_loss += float(self.CRITERION(out, batch.to(device))) / len(
                        batch
                    )

                self.LOGGER.info("Test Loss: %s", test_loss)
        else:
            test_loss = None

        artifact = TrainArtifact(
            model=autoencoder,
            train_losses=train_losses,
            baseline_loss=baseline_loss,
            test_loss=test_loss,
        )

        return artifact
