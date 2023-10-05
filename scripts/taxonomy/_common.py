import argparse
from pathlib import Path

def dataset_args(parser: argparse.ArgumentParser):
    group = parser.add_argument_group("Dataset")
    group.add_argument("--synthetic-data-path", type=Path, required=True)
    group.add_argument("--dataset", type=str, required=True)
    group.add_argument("--synthetic-classifier", type=str, required=True)
    group.add_argument("--distribution", type=str, required=True, choices=["presence-absence", "natural"])


def make_output_path(config: argparse.Namespace):
    Path(config.output_path).mkdir(exist_ok=True)
    output_path = config.output_path / config.dataset / config.synthetic_classifier / config.distribution
    output_path.mkdir(exist_ok=True, parents=True)
    return output_path


def find_fastas_to_process(
    synthetic_data_path: Path,
    dataset: str,
    synthetic_classifier: str,
    distribution: str,
    output_path
):
    path = synthetic_data_path / dataset / synthetic_classifier / f"test-{distribution}"
    existing = set([f.name for f in output_path.iterdir() if f.name.endswith(".tax.tsv")])
    return set([f for f in path.iterdir() if f.name.endswith(".fasta") and f.with_suffix(".tax.tsv").name not in existing])


def read_fasta(path: Path):
    with open(path) as f:
        header = f.readline()
        while header != "":
            identifier = header[1:].split(maxsplit=1)[0]
            sequence = f.readline().strip()
            header = f.readline()
            yield identifier, sequence


def write_tax_tsv(path: Path, entries):
    with open(path, 'w') as f:
        for identifier, label in entries:
            f.write(f"{identifier}\t{label}\n")
