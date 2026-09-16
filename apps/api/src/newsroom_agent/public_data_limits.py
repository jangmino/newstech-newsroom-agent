"""Per-provider HTTP admission limits; process memory only, no queue or retries."""

from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from math import ceil
from threading import Lock
from time import monotonic
from typing import Literal

PublicDataSource = Literal["kosis", "opendart"]


class PublicDataLimitError(Exception):
    def __init__(self, source: PublicDataSource, retry_after_seconds: int | None) -> None:
        self.source = source
        self.retry_after_seconds = retry_after_seconds
        self.code = "public_data_rate_limited" if retry_after_seconds else "public_data_busy"
        label = {"kosis": "KOSIS", "opendart": "OpenDART"}[source]
        reason = (
            f"현재 서버의 {label} 조회 요청 한도에 도달했습니다." if retry_after_seconds
            else f"현재 서버에서 {label} 자료를 조회하는 요청이 많습니다."
        )
        super().__init__(
            f"{reason} 입력한 조건은 유지됩니다. 자동으로 다시 조회하지 않습니다. "
            "잠시 후 ‘이 조건으로 조회’를 다시 눌러 주세요."
        )


class PublicDataCallLimiter:
    def __init__(
        self, source: PublicDataSource, requests_per_minute: int, max_concurrent: int, *,
        timer: Callable[[], float] = monotonic,
    ) -> None:
        if source not in ("kosis", "opendart"):
            raise ValueError("Invalid public data source")
        if type(requests_per_minute) is not int or not 1 <= requests_per_minute <= 300:
            raise ValueError("Invalid public data request limit")
        if type(max_concurrent) is not int or not 1 <= max_concurrent <= 30:
            raise ValueError("Invalid public data concurrency limit")
        self._source = source
        self._requests_per_minute = requests_per_minute
        self._max_concurrent = max_concurrent
        self._timer = timer
        self._starts: deque[float] = deque()
        self._active = 0
        self._lock = Lock()

    @contextmanager
    def slot(self) -> Iterator[None]:
        # Never hold the lock across I/O. Admission is atomic even across threads.
        with self._lock:
            now = self._timer()
            while self._starts and now - self._starts[0] >= 60:
                self._starts.popleft()
            if len(self._starts) >= self._requests_per_minute:
                raise PublicDataLimitError(self._source, max(1, ceil(60 - (now - self._starts[0]))))
            if self._active >= self._max_concurrent:
                raise PublicDataLimitError(self._source, None)
            self._starts.append(now)
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
