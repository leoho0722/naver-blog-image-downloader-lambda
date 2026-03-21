from dataclasses import dataclass
from typing import Any


@dataclass
class DownloadResult:
    total_images: int
    successful_downloads: int
    failure_downloads: int
    image_urls: list[str]
    errors: list[str]
    elapsed_time: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        result = {k: v for k, v in vars(self).items() if k != "elapsed_time"}
        result["elapsed_time"] = round(self.elapsed_time, 2)
        return result
