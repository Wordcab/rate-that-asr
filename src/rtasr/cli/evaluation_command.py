"""The evaluation command."""

import argparse
import asyncio
from pathlib import Path
from typing import Dict, List, Union

from rich import print
from rich.live import Live
from rich.progress import Progress

from rtasr.cli_messages import error_message
from rtasr.constants import DATASETS, PROVIDERS, Metrics
from rtasr.evaluation import DerResult, evaluate_der
from rtasr.utils import create_live_panel, get_files, resolve_cache_dir


def evaluation_command_factory(args: argparse.Namespace):
    return EvaluationCommand(
        metrics=args.metrics,
        dataset=args.dataset,
        split=args.split,
        dataset_dir=args.dataset_dir,
        transcription_dir=args.transcription_dir,
        output_dir=args.output_dir,
        use_cache=args.no_cache,
        debug=args.debug,
    )


class EvaluationCommand:
    """List items."""

    @staticmethod
    def register_subcommand(parser: argparse.ArgumentParser) -> None:
        """Register the subcommand."""
        subparser = parser.add_parser("evaluation", help="Run evaluation on a dataset.")
        subparser.add_argument(
            "-m",
            "--metric",
            help="The metric to use. `rtasr list -t metrics` for more info.",
            required=True,
            type=str,
        )
        subparser.add_argument(
            "-d",
            "--dataset",
            help="The dataset to run evaluation on.",
            required=True,
            type=str,
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
            "--transcription_dir",
            help=(
                "Path where the transcription files are stored. Defaults to"
                " `~/.cache/rtasr/transcription`."
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
        subparser.add_argument(
            "--debug",
            help="Whether to run in debug mode or not.",
            required=False,
            action="store_true",
        )
        subparser.set_defaults(func=evaluation_command_factory)

    def __init__(
        self,
        metric: List[str],
        dataset: str,
        split: str,
        dataset_dir: Union[str, None] = None,
        transcription_dir: Union[str, None] = None,
        output_dir: Union[str, None] = None,
        use_cache: bool = True,
        debug: bool = False,
    ) -> None:
        """Initialize the command."""
        self.metric = metric
        self.dataset = dataset
        self.split = split
        self.dataset_dir = dataset_dir
        self.transcription_dir = transcription_dir
        self.output_dir = output_dir
        self.use_cache = use_cache
        self.debug = debug

    def run(self) -> None:
        """Run the command."""
        try:
            if self.dataset.lower() not in DATASETS.keys():
                print(
                    error_message.format(input_type="dataset", user_input=self.dataset)
                )
                print("".join([f"  - [bold]{d}[bold]\n" for d in DATASETS.keys()]))
                exit(1)

            if self.metric.upper() not in Metrics.__members__.keys():
                print(error_message.format(input_type="metric", user_input=self.metric))
                print(
                    "".join(
                        [f"  - [bold]{m}[bold]\n" for m in Metrics.__members__.keys()]
                    )
                )
                exit(1)

            _providers = list(PROVIDERS.keys())
            _dataset = self.dataset.lower()
            _metric = Metrics[self.metric.upper()]

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

            if self.transcription_dir is None:
                transcription_dir = resolve_cache_dir() / "transcription" / _dataset
            else:
                transcription_dir = (
                    Path(self.transcription_dir) / "transcription" / _dataset
                )

            if not transcription_dir.exists():
                print(
                    "Transcription directory does not exist:"
                    f" {transcription_dir.resolve()}\nPlease check"
                    " `rtasr transcription --help` to run transcription on the"
                    " dataset."
                )
                exit(1)

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

            if self.output_dir is None:
                output_dir = resolve_cache_dir() / "evaluation"
            else:
                output_dir = Path(self.output_dir) / "evaluation"

            evaluation_dir = output_dir / _dataset
            if not evaluation_dir.exists():
                evaluation_dir.mkdir(parents=True, exist_ok=True)

            if _metric == Metrics.DER:
                ref_rttm_filepaths: Dict[str, List[Path]] = {s: [] for s in splits}
                for split in splits:
                    _path = dataset_dir / DATASETS[_dataset]["rttm_filepaths"][split]
                    ref_rttm_filepaths[split].extend(
                        [Path(f) for f in get_files(_path) if f.suffix == ".rttm"]
                    )

                func_to_run = self._run_der
                func_args = {"rttm_filepaths": ref_rttm_filepaths}

            elif _metric == Metrics.WER:
                func_to_run = self._run_wer
                func_args = {}

                print("🚧 WER not implemented yet.")
                exit(1)

            (
                current_progress,
                step_progress,
                splits_progress,
                progress_group,
            ) = create_live_panel()

            with Live(progress_group):
                current_progress_task_id = current_progress.add_task(
                    f"Running evaluation {_metric} over the `{_dataset}` dataset"
                )
                results = asyncio.run(
                    func_to_run(
                        **func_args,
                        providers=_providers,
                        evaluation_dir=evaluation_dir,
                        transcription_dir=transcription_dir,
                        splits_progress=splits_progress,
                        step_progress=step_progress,
                        use_cache=self.use_cache,
                        debug=self.debug,
                    )
                )

                current_progress.stop_task(current_progress_task_id)
                current_progress.update(
                    current_progress_task_id,
                    description="[bold green]Evaluations finished.",
                )

            print(f"Find the evaluation results in {evaluation_dir.resolve()}")
            print(
                "Results by provider:"
                " [green]evaluated[/green]/[cyan]cached[/cyan]/[red]not_found[/red]"
            )

            for result in results:
                if not isinstance(result, Exception):
                    print(
                        f"- {result.provider_name}:"
                        f" [green]{result.evaluated}[/green]/[cyan]{result.cached}[/cyan]/[red]{result.not_found}[/red]"
                    )
                else:
                    print(f"[red]Error: {result}[/red]")

        except KeyboardInterrupt:
            print("\n[bold red]Cancelled by user.[/bold red]\n")
            exit(1)

        except Exception as e:
            raise Exception(e) from e

    async def _run_der(
        self,
        rttm_filepaths: Dict[str, List[Path]],
        providers: List[str],
        evaluation_dir: Path,
        transcription_dir: Path,
        splits_progress: Progress,
        step_progress: Progress,
        use_cache: bool,
        debug: bool,
    ) -> None:
        """
        Run the evaluation for the Diarization Error Rate (DER).

        TODO: Add docstrings
        TODO: Add return type
        """
        splits_progress_task_id = splits_progress.add_task(
            "",
            total=len(rttm_filepaths),
        )

        tasks = [
            evaluate_der(
                split_name=split,
                split_rttm_files=rttm_filepaths[split],
                providers=providers,
                evaluation_dir=evaluation_dir,
                transcription_dir=transcription_dir,
                split_progress=splits_progress,
                split_progress_task_id=splits_progress_task_id,
                step_progress=step_progress,
                use_cache=use_cache,
                debug=debug,
            )
            for split in rttm_filepaths.keys()
        ]
        results: List[DerResult] = await asyncio.gather(*tasks, return_exceptions=True)

        splits_progress.update(splits_progress_task_id, visible=False)

        return results

    async def _run_wer(
        self,
        providers: List[str],
        evaluation_dir: Path,
        transcription_dir: Path,
        splits_progress: Progress,
        step_progress: Progress,
        use_cache: bool,
        debug: bool,
    ) -> None:
        """
        Run the evaluation for the Word Error Rate (WER).

        TODO: Add docstrings
        TODO: Add return type
        """
        pass
