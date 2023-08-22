"""The transcription command to run ASR providers against a dataset."""

import argparse
import asyncio
import importlib
import json
from pathlib import Path
from typing import Dict, List, Tuple, Union

import aiohttp
from rich import print
from rich.live import Live
from rich.progress import Progress

from rtasr.asr import ASRProvider, ProviderResult
from rtasr.cli_messages import error_message
from rtasr.constants import DATASETS, PROVIDERS
from rtasr.utils import create_live_panel, get_api_key, resolve_cache_dir


def transcription_asr_command_factory(args: argparse.Namespace):
    return TranscriptionASRCommand(
        args.providers,
        args.dataset,
        args.split,
        args.dataset_dir,
        args.output_dir,
        args.no_cache,
    )


class TranscriptionASRCommand:
    """Launc transcription for one or multiple ASR providers against a dataset."""

    @staticmethod
    def register_subcommand(parser: argparse.ArgumentParser) -> None:
        subparser = parser.add_parser(
            "transcription",
            help="Launch transcription for one or multiple ASR providers against a dataset.",
        )
        subparser.add_argument(
            "-p",
            "--providers",
            help=(
                "The ASR provider(s) to call. You can specify multiple providers."
            ),
            required=True,
            type=str,
            nargs="+",
        )
        subparser.add_argument(
            "-d", "--dataset", help="The dataset to use.", required=True, type=str
        )
        subparser.add_argument(
            "-s",
            "--split",
            help="The split to use. `rtasr list -t datasets` for more info.",
            required=False,
            default="all",
            type=str,
        )
        subparser.add_argument(
            "--dataset_dir",
            help=(
                "Path where the dataset files are stored. Defaults to"
                " `~/.cache/rtasr/datasets`."
            ),
            required=False,
            default=None,
            type=str,
        )
        subparser.add_argument(
            "-o",
            "--output_dir",
            help=(
                "Path where store the transcription outputs. Defaults to"
                " `~/.cache/rtasr/transcription`."
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
        subparser.set_defaults(func=transcription_asr_command_factory)

    def __init__(
        self,
        providers: List[str],
        dataset: str,
        split: str,
        dataset_dir: Union[str, None] = None,
        output_dir: Union[str, None] = None,
        use_cache: bool = True,
    ) -> None:
        """Initialize the command."""
        self.providers = providers
        self.dataset = dataset
        self.split = split
        self.dataset_dir = dataset_dir
        self.output_dir = output_dir
        self.use_cache = use_cache

    def run(self) -> None:
        """Run the command.

        Raises:
            Exception: If the command fails.

        """
        try:
            for provider in self.providers:
                if provider.lower() not in PROVIDERS.keys():
                    print(
                        error_message.format(input_type="provider", user_input=provider)
                    )
                    print("".join([f"  - [bold]{p}[bold]\n" for p in PROVIDERS.keys()]))
                    exit(1)

            if self.dataset.lower() not in DATASETS.keys():
                print(
                    error_message.format(input_type="dataset", user_input=self.dataset)
                )
                print("".join([f"  - [bold]{d}[bold]\n" for d in DATASETS.keys()]))
                exit(1)

            _providers = [p.lower() for p in self.providers]
            _dataset = self.dataset.lower()

            if self.dataset_dir is None:
                dataset_dir = resolve_cache_dir() / "datasets" / _dataset
            else:
                dataset_dir = Path(self.dataset_dir) / "datasets" / _dataset

            if not dataset_dir.exists():
                print(
                    f"Dataset directory does not exist: {dataset_dir.resolve()}\nPlease"
                    f" run `rtasr download -d {_dataset} --no-cache` to download the"
                    " dataset."
                )
                exit(1)

            print(
                rf"Dataset [bold green]\[{_dataset}][/bold green] from"
                f" {dataset_dir.resolve()}"
            )

            splits: List[str] = []
            if self.split.lower() == "all":
                splits.extend(DATASETS[self.dataset.lower()]["splits"])
            elif self.split.lower() in DATASETS[self.dataset.lower()]["splits"]:
                splits.append(self.split.lower())
            else:
                print(error_message.format(input_type="split", user_input=self.split))
                print(
                    "".join(
                        [
                            f"  - [bold]{s}[bold]\n"
                            for s in DATASETS[self.dataset.lower()]["splits"]
                        ]
                    )
                )
                exit(1)

            print(f"Using splits: {splits}")

            all_manifest_filepaths = DATASETS[_dataset]["manifest_filepaths"]

            selected_manifest_filepaths: List[Tuple[str, Path]] = []
            for split in splits:
                for filepath in all_manifest_filepaths[split]:
                    manifest_filepath = dataset_dir / filepath

                    if not manifest_filepath.exists():
                        print(
                            "Manifest file does not exist:"
                            f" {manifest_filepath.resolve()}\nPlease run `rtasr"
                            f" download -d {_dataset} --no-cache` to download the"
                            " dataset."
                        )
                        exit(1)
                    else:
                        selected_manifest_filepaths.append((split, manifest_filepath))

            print(
                f"Manifest filepaths: {len(selected_manifest_filepaths)} files found."
            )

            audio_filepaths: Dict[str, List[Path]] = {s: [] for s in splits}
            for split, manifest_filepath in selected_manifest_filepaths:
                with open(manifest_filepath, "r") as f:
                    manifest = json.load(f)

                audio_filepaths[split].extend(
                    [Path(m["audio_filepath"]) for m in manifest]
                )

            verified_audio_filepaths: Dict[str, List[Path]] = {s: [] for s in splits}
            for split, filepaths in audio_filepaths.items():
                verified_audio_filepaths[split] = [
                    audio_filepath
                    for audio_filepath in filepaths
                    if audio_filepath.exists()
                ]

                print(
                    rf"    \[{split}] Audio files: [bold"
                    f" green]{len(verified_audio_filepaths[split])}[/bold"
                    f" green]/{len(audio_filepaths[split])} (found/total)"
                )

            if self.output_dir is None:
                output_dir = resolve_cache_dir() / "transcription"
            else:
                output_dir = Path(self.output_dir) / "transcription"

            transcription_dir = output_dir / _dataset
            if not transcription_dir.exists():
                transcription_dir.mkdir(parents=True, exist_ok=True)

            engines: List[ASRProvider] = []
            for _provider in _providers:
                engine_class = getattr(
                    importlib.import_module("rtasr.asr.providers"),
                    PROVIDERS[_provider].get("engine", None),
                )

                _api_key: Union[str, None] = get_api_key(_provider)
                if _api_key is not None:
                    engines.append(
                        engine_class(
                            api_url=PROVIDERS[_provider].get("url", None),
                            api_key=_api_key,
                            options=PROVIDERS[_provider].get("options", {}),
                            concurrency_limit=PROVIDERS[_provider].get(
                                "concurrency_limit", None
                            ),
                        )
                    )

            (
                current_progress,
                step_progress,
                splits_progress,
                progress_group,
            ) = create_live_panel()

            with Live(progress_group):
                current_progress_task_id = current_progress.add_task(
                    f"Running transcription over the `{_dataset}` dataset"
                )
                results = asyncio.run(
                    self._run(
                        engines,
                        verified_audio_filepaths,
                        transcription_dir,
                        splits_progress,
                        step_progress,
                    )
                )

                current_progress.stop_task(current_progress_task_id)
                current_progress.update(
                    current_progress_task_id,
                    description="[bold green]Transcriptions finished.",
                )

            print(f"Find the transcription results in {transcription_dir.resolve()}")
            print("Results by provider: [green]completed[/green]|[red]failed[/red]")

            for result in results:
                if not isinstance(result, Exception):
                    print(
                        f"- {result.provider_name}:"
                        f" [green]{result.completed}[/green]|[red]{result.failed}[/red]"
                    )
                else:
                    print(f"[red]Error: {result}[/red]")

        except KeyboardInterrupt:
            print("\n[bold red]Cancelled by user.[/bold red]\n")
            exit(1)
        except Exception as e:
            raise Exception(e) from e

    async def _run(
        self,
        engines: List[ASRProvider],
        audio_files: Dict[str, List[Path]],
        output_dir: Path,
        splits_progress: Progress,
        step_progress: Progress,
    ) -> List[ProviderResult]:
        splits_progress_task_id = splits_progress.add_task("", total=len(engines))

        timeout = aiohttp.ClientTimeout(total=1800)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = [
                engine.launch(
                    audio_files=audio_files,
                    output_dir=output_dir,
                    session=session,
                    split_progress=splits_progress,
                    split_progress_task_id=splits_progress_task_id,
                    step_progress=step_progress,
                )
                for engine in engines
            ]
            results: List[ProviderResult] = await asyncio.gather(
                *tasks, return_exceptions=True
            )

        splits_progress.update(splits_progress_task_id, visible=False)

        return results