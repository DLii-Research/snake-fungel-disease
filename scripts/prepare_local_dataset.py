#!/usr/bin/env python3
"""
Prepare a local dataset given FASTA/FASTQ files. This script can automatically create shuffled
training/testing splits of the given FASTA/FASTQ files, outputting the desired FASTA/FASTQ or
DB files.
"""
from dnadb import dna, fasta, fastq
from dnadb.utils import compress
import numpy as np
from pathlib import Path
import re
import sys
import tf_utilities.scripting as tfs
from tqdm.auto import tqdm, trange

import bootstrap

def define_arguments(cli: tfs.CliArgumentFactory):
    cli.use_rng()
    cli.argument("output_path", help="The path where the files will be written")
    cli.argument("data_files", nargs='+', help="Paths to FASTA/FASTQ files")
    cli.argument("--test-split", type=float, default=0.2, help="The factor of the number of samples to use for testing")
    cli.argument("--num-splits", type=int, default=1, help=f"The number of data splits to create")
    processing = cli.parser.add_argument_group("Processing Steps")
    processing.add_argument("--clean-sequences", default=False, action="store_true", help="Clean the sequences by removing any unknown characters")
    output_types = cli.parser.add_argument_group("Output Formats")
    output_types.add_argument("--output-db", default=False, action="store_true", help="Output FASTA DBs")
    output_types.add_argument("--output-fasta-fastq", default=False, action="store_true", help="Output FASTA files")
    output_types.add_argument("--compress", default=False, action="store_true", help="Compress the output FASTA/TSV files")


def output_fasta_file(
    config,
    filename: str,
    entries: list[fasta.FastaEntry],
    split_index: int,
    output_path: Path,
):
    train_path = output_path
    files: list[Path] = []
    if config.test_split > 0.0:
        test_path = output_path / "test"
        train_path = output_path / "train"
        with open(test_path / filename, 'w') as f:
            fasta.write(f, tqdm(entries[:split_index], leave=False, desc="Writing test FASTA"))
            files.append(Path(f.name))
    with open(train_path / filename, 'w') as f:
        fasta.write(f, tqdm(entries[split_index:], leave=False, desc="Writing train FASTA"))
        files.append(Path(f.name))
    return files


def output_fastq_file(
    config,
    filename: str,
    entries: list[fastq.FastqEntry],
    split_index: int,
    output_path: Path,
):
    train_path = output_path
    files: list[Path] = []
    if config.test_split > 0.0:
        test_path = output_path / "test"
        train_path = output_path / "train"
        with open(test_path / filename, 'w') as f:
            fastq.write(f, tqdm(entries[:split_index], leave=False, desc="Writing test FASTQ"))
            files.append(Path(f.name))
    with open(train_path / filename, 'w') as f:
        fastq.write(f, tqdm(entries[split_index:], leave=False, desc="Writing train FASTQ"))
        files.append(Path(f.name))
    return files


def output_fasta_db(
    config,
    filename: str,
    entries: list[fasta.FastaEntry],
    split_index: int,
    output_path: Path,
):
    train_path = output_path
    if config.test_split > 0.0:
        test_path = output_path / "test"
        train_path = output_path / "train"
        db = fasta.FastaDbFactory(test_path / filename)
        db.write_entries(tqdm(entries[:split_index], leave=False, desc="Writing test FASTA DB"))
    db = fasta.FastaDbFactory(train_path / filename)
    db.write_entries(tqdm(entries[split_index:], leave=False, desc="Writing train FASTA DB"))


def output_fastq_db(
    config,
    filename: str,
    entries: list[fastq.FastqEntry],
    split_index: int,
    output_path: Path,
):
    train_path = output_path
    if config.test_split > 0.0:
        test_path = output_path / "test"
        train_path = output_path / "train"
        db = fastq.FastqDbFactory(test_path / filename)
        db.write_entries(tqdm(entries[:split_index], leave=False, desc="Writing test FASTQ DB"))
    db = fastq.FastqDbFactory(train_path / filename)
    db.write_entries(tqdm(entries[split_index:], leave=False, desc="Writing train FASTQ DB"))


def process_fasta_files(
    config,
    fasta_files: list[Path],
    output_path: Path,
    rng: np.random.Generator
):
    files: list[Path] = []
    for fasta_file in tqdm(fasta_files, desc="Procesing FASTA"):
        entries = list(tqdm(fasta.entries(fasta_file), desc=f"Reading {fasta_file.name}"))
        if config.clean_sequences:
            for entry in tqdm(entries, desc="Cleaning sequences"):
                entry.sequence = re.sub(f"[^{dna.ALL_BASES}]", '', entry.sequence)
        split_index = int(len(entries) * config.test_split)
        filename = fasta_file.name.rstrip('.gz')
        for i in trange(config.num_splits, desc="Split"):
            rng.shuffle(entries) # type: ignore
            path = (output_path / str(i)) if config.test_split > 0.0 else output_path
            if config.output_fasta_fastq:
                files += output_fasta_file(config, filename, entries, split_index, path)
            if config.output_db:
                output_fasta_db(config, filename, entries, split_index, path)
    return files


def process_fastq_files(
    config,
    fastq_files: list[Path],
    output_path: Path,
    rng: np.random.Generator
):
    files: list[Path] = []
    for fastq_file in tqdm(fastq_files, desc="Procesing FASTQ"):
        entries = list(tqdm(fastq.entries(fastq_file), desc=f"Reading {fastq_file.name}"))
        split_index = int(len(entries) * config.test_split)
        filename = fastq_file.name.rstrip('.gz')
        for i in trange(config.num_splits, desc="Split"):
            rng.shuffle(entries) # type: ignore
            path = (output_path / str(i)) if config.test_split > 0.0 else output_path
            if config.output_fasta_fastq:
                files += output_fastq_file(config, filename, entries, split_index, path)
            if config.output_db:
                output_fastq_db(config, filename, entries, split_index, path)
    return files


def main():
    config = tfs.init(define_arguments, use_wandb=False)

    # Check the output path
    output_path = Path(config.output_path)
    if not output_path.parent.exists():
        print(f"The output directory: `{output_path.parent}` does not exist.")
        return 1

    if config.num_splits > 1 and config.test_split == 0.0:
        print("Num splits can only be used when a test split > 0.0 is supplied.")
        return 1

    if not config.output_fasta_fastq and not config.output_db:
        print("You must select at least one output type.")
        return 1

    # Check FASTA and FASTQ files
    fasta_files: list[Path] = []
    fastq_files: list[Path] = []
    for file in map(Path, config.data_files):
        if not file.exists():
            print("File does not exist:", file)
            return 1
        if file.name.endswith(".fasta") or file.name.endswith(".fasta.gz"):
            fasta_files.append(file)
        elif file.name.endswith(".fastq") or file.name.endswith(".fastq.gz"):
            fastq_files.append(file)
        else:
            print("Unknown file type:", file)
            return 1

    # Create the directories
    for i in range(config.num_splits):
        train_path = output_path
        test_path = None
        if config.test_split > 0.0:
            train_path = output_path / str(i)
            test_path = train_path / "test"
            train_path = train_path / "train"
            test_path.mkdir(parents=True, exist_ok=True)
        train_path.mkdir(parents=True, exist_ok=True)

    rng = tfs.rng()
    files_written: list[Path] = []
    if len(fasta_files) > 0:
        files_written += process_fasta_files(config, fasta_files, output_path, rng)
    if len(fastq_files) > 0:
        files_written += process_fastq_files(config, fastq_files, output_path, rng)

    if config.compress:
        for file in tqdm(files_written, desc="Compressing files"):
            compress(file)


if __name__ == "__main__":
    sys.exit(main())
