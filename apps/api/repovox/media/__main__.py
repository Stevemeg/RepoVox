"""python -m repovox.media: local repository commit -> narrated explanation video."""

import argparse
import sys
from pathlib import Path

from repovox.analysis.common import AnalysisError
from repovox.media.local import analyze
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
    args = parser.parse_args()
    try:
        payload = analyze(
            args.git_repository.resolve(), args.repository_url, args.revision, tuple(args.path)
        )
        video = produce(payload, args.output, source_note="local-git-archive")
    except (AnalysisError, GroundingError, NarrationError, RenderError, LayoutError) as error:
        print(f"failed: {error.code}", file=sys.stderr)  # Fixed codes only; no source text.
        raise SystemExit(1) from None
    print(video)


if __name__ == "__main__":
    main()
