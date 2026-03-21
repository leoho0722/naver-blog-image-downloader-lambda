from dataclasses import dataclass
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    """非同步任務狀態"""

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


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
