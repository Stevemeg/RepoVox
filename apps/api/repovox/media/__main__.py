"""python -m repovox.media: local repository commit -> narrated explanation videos."""

import argparse
import sys
from pathlib import Path

from repovox.analysis.common import AnalysisError
from repovox.media.architecture import ArchitectureError, discover
from repovox.media.explainer import explain
from repovox.media.local import analyze_with_sources
from repovox.media.narration import NarrationError
from repovox.media.raster import LayoutError
from repovox.media.render import RenderError, produce
from repovox.media.storyboard import GroundingError


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m repovox.media", description=__doc__)
    parser.add_argument("--git-repository", required=True, type=Path, help="local Git repository")
    parser.add_argument("--repository-url", required=True, help="https://github.com/owner/name")
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--path", action="append", default=[], help="limit to a subdirectory")
    parser.add_argument("--output", required=True, type=Path, help="new absolute directory")
    parser.add_argument(
        "--architecture-only", action="store_true", help="skip the repository walkthrough video"
    )
    args = parser.parse_args()
    try:
        payload, sources = analyze_with_sources(
            args.git_repository.resolve(), args.repository_url, args.revision, tuple(args.path)
        )
        report = discover(payload, sources)
        if args.architecture_only:
            if not args.output.is_absolute() or not args.output.parent.is_dir():
                raise RenderError("output_must_be_new_absolute_directory")
            args.output.mkdir(mode=0o700)
        else:
            print(produce(payload, args.output, source_note="local-git-archive"))
        manifest = explain(report, payload, sources, args.output / "architecture")
    except (
        AnalysisError,
        ArchitectureError,
        GroundingError,
        NarrationError,
        RenderError,
        LayoutError,
        FileExistsError,
    ) as error:
        code = getattr(error, "code", "output_must_be_new_absolute_directory")
        print(f"failed: {code}", file=sys.stderr)  # Fixed codes only; no source text.
        raise SystemExit(1) from None
    bundle = args.output / "architecture" / "published"
    if manifest["architecture_explanation"] == "unsupported":
        reasons = ", ".join(r["reason"] for r in manifest["rejected"]) or "no_pattern_established"
        print(f"architecture explanation: unsupported ({reasons})")
    for item in manifest["architectures"]:
        print(bundle / item["id"] / "video.mp4")
    print(bundle / "architecture-report.json")


if __name__ == "__main__":
    main()
