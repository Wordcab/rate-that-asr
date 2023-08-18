"""The download command."""

import argparse
import asyncio
from typing import Union

from rtasr.cli_messages import error_message
from rtasr.constants import DATASETS


def download_dataset_command_factory(args: argparse.Namespace):
    return DownloadDatasetCommand(args.dataset, args.output_dir, args.no_cache)


class DownloadDatasetCommand:
    """Download a dataset."""

    @staticmethod
    def register_subcommand(parser: argparse.ArgumentParser) -> None:
        subparser = parser.add_parser("download", help="Download a dataset.")
        subparser.add_argument(
            "-d", "--dataset", help="The dataset to download.", required=True, type=str
        )
        subparser.add_argument(
            "-o",
            "--output_dir",
            help=(
                "Path to store the downloaded files. Defaults to"
                " `~/.cache/rtasr/datasets`."
            ),
            required=False,
            default=None,
            type=str,
        )
        subparser.add_argument(
            "--no-cache",
            help="Whether to use the cache or not.",
            required=False,
            action="store_false",
        )
        subparser.set_defaults(func=download_dataset_command_factory)

    def __init__(
        self,
        dataset: str,
        output_dir: Union[str, None] = None,
        use_cache: bool = True,
    ) -> None:
        """Initialize the command."""
        self.dataset = dataset
        self.output_dir = output_dir
        self.use_cache = use_cache

    def run(self) -> None:
        """Run the command."""
        try:
            if self.dataset.lower() == "ami":
                from rtasr.datasets import prepare_ami_dataset

                asyncio.run(prepare_ami_dataset(self.output_dir, self.use_cache))

            elif self.dataset.lower() == "voxconverse":
                from rtasr.datasets import prepare_voxconverse_dataset

                asyncio.run(
                    prepare_voxconverse_dataset(self.output_dir, self.use_cache)
                )

            else:
                print(
                    error_message.format(input_type="dataset", user_input=self.dataset)
                )
                print("".join([f"  - [bold]{d}[bold]\n" for d in DATASETS.keys()]))
                exit(1)
        except KeyboardInterrupt:
            print("\n[bold red]Cancelled by user.[/bold red]\n")
            exit(1)
        except Exception as e:
            raise Exception(e) from e
