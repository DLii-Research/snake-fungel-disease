import argparse
from dnadb import sample
import deepctx.scripting as dcs
from deepctx.lazy import tensorflow as tf
import numpy as np
import pandas as pd
from pathlib import Path
from deepdna.nn import data_generators as dg
from deepdna.nn.metrics import f1_score, negative_predictive_value
from deepdna.nn.models import load_model
from deepdna.nn.models.setbert import SetBertEncoderModel, SetBertPretrainModel


class PersistentSetBertSfdModel(dcs.module.Wandb.PersistentObject["tf.keras.models.Model"]):
    def create(self, config: argparse.Namespace):
        # Create the model
        wandb = self.context.get(dcs.module.Wandb)
        setbert_pretrain_path = wandb.artifact_argument_path("setbert_pretrain")
        setbert_base = load_model(setbert_pretrain_path, SetBertPretrainModel).base
        setbert_encoder = SetBertEncoderModel(
            setbert_base,
            compute_sequence_embeddings=True,
            stop_sequence_embedding_gradient=True,
            output_class=True,
            output_sequences=False)
        model = tf.keras.Sequential([
            setbert_encoder,
            tf.keras.layers.Dense(1, activation="sigmoid")
        ])
        model.compile(
            metrics=[
                tf.keras.metrics.BinaryAccuracy(),
                tf.keras.metrics.Precision(name="precision_ppv"),
                tf.keras.metrics.Recall(),
                f1_score,
                negative_predictive_value
            ],
            loss=tf.keras.losses.BinaryCrossentropy(),
            optimizer=tf.keras.optimizers.Adam(config.lr),
        )
        setbert_encoder.chunk_size = 256
        return model

    def load(self):
        return load_model(self.path("model"), tf.keras.models.Model[SetBertEncoderModel])

    def save(self):
        self.instance.save(self.path("model"))

    def to_artifact(self, name: str):
        wandb = self.context.get(dcs.module.Wandb).wandb
        artifact = wandb.Artifact(name, type="model")
        artifact.add_dir(str(self.path("model")))
        return artifact


def define_arguments(context: dcs.Context):
    parser = context.argument_parser
    group = parser.add_argument_group("Dataset Settings")
    group.add_argument("--sfd-dataset-path", type=Path, help="The path to the SFD dataset directory.")
    group.add_argument("--subsample-size", type=int, default=1000, help="The number of sequences per subsample")

    group = parser.add_argument_group("Model Settings")
    group.add_argument("--lr", type=float, default=1e-4, help="The learning rate to use for training.")

    wandb = context.get(dcs.module.Wandb)
    wandb.add_artifact_argument("setbert-pretrain", required=True)

    group = wandb.argument_parser.add_argument_group("Logging")
    group.add_argument("--log-artifact", type=str, default=None, help="Log the model as a W&B artifact.")


def data_generators(config: argparse.Namespace, sequence_length: int, kmer: int):
    metadata = pd.read_csv(config.sfd_dataset_path / f"{config.sfd_dataset_path.name}.metadata.csv")
    targets = dict(zip(metadata["swab_label"], metadata["oo_present"]))
    samples = [s for s in sample.load_multiplexed_fasta(
        config.sfd_dataset_path / f"{config.sfd_dataset_path.name}.fasta.db",
        config.sfd_dataset_path / f"{config.sfd_dataset_path.name}.fasta.mapping.db",
        config.sfd_dataset_path / f"{config.sfd_dataset_path.name}.fasta.index.db"
    ) if s.name in targets]
    # Remove any missing samples without targets
    to_keep = set(s.name for s in samples) & set(targets.keys())
    samples = [s for s in samples if s.name in to_keep]
    targets = {s.name: targets[s.name] for s in samples}
    num_positive = sum(targets.values())
    num_negative = len(targets) - num_positive
    class_weights = np.array([0.5 / num_positive if targets[s.name] else 0.5 / num_negative for s in samples])
    print(f"Found {len(samples)} samples.")
    print(f"Positive: {num_positive}, Negative: {num_negative}")
    generator_pipeline = [
        lambda batch_size, np_rng: dict(samples=np_rng.choice(samples, batch_size, p=class_weights, replace=True)),
        dg.random_sequence_entries(subsample_size=config.subsample_size),
        dg.sequences(length=sequence_length),
        dg.augment_ambiguous_bases,
        dg.encode_sequences(),
        dg.encode_kmers(kmer),
        lambda samples, encoded_kmer_sequences: (
            encoded_kmer_sequences,
            np.array([targets[s.name] for s in samples]))
    ]
    train_data = dg.BatchGenerator(
        config.batch_size,
        config.steps_per_epoch,
        generator_pipeline)
    val_data = dg.BatchGenerator(
        config.val_batch_size,
        config.val_steps_per_epoch,
        generator_pipeline,
        shuffle=False)
    return train_data, val_data

def main(context: dcs.Context):
    config = context.config

    # with context.get(dcs.module.Tensorflow).strategy().scope():

    # Get the model instance
    model = PersistentSetBertSfdModel()

    # Training
    if config.train:
        print("Training model...")
        setbert_encoder: SetBertEncoderModel = model.instance.layers[0]
        train_data, val_data = data_generators(
            config,
            setbert_encoder.sequence_length,
            setbert_encoder.kmer)
        model.path("model").mkdir(exist_ok=True, parents=True)
        context.get(dcs.module.Train).fit(
            model.instance,
            train_data,
            validation_data=val_data,
            callbacks=[
                tf.keras.callbacks.ModelCheckpoint(filepath=str(model.path("model"))),
                context.get(dcs.module.Wandb).wandb.keras.WandbMetricsLogger()
            ])

    # Artifact logging
    if config.log_artifact is not None:
        print("Logging artifact...")
        model.instance # Load the model to ensure it is in-tact
        artifact = model.to_artifact(config.log_artifact)
        context.get(dcs.module.Wandb).log_artifact(artifact)


if __name__ == "__main__":
    context = dcs.Context(main)
    context.use(dcs.module.Tensorflow)
    context.use(dcs.module.Train) \
        .optional_training() \
        .use_steps() \
        .defaults(
            epochs=None,
            batch_size=3,
            steps_per_epoch=100,
            val_steps_per_epoch=20)
    context.use(dcs.module.Rng)
    context.use(dcs.module.Wandb)
    define_arguments(context)
    context.execute()
