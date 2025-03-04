import datetime
import math
import sys
import time
from collections import defaultdict
from functools import wraps
from typing import Optional, Union, Callable

from .logger import JinaLogger
from ..helper import colored, get_readable_size, get_readable_time


def used_memory(unit: int = 1024 * 1024 * 1024) -> float:
    """
    Get the memory usage of the current process.

    :param unit: Unit of the memory, default in Gigabytes.
    :return: Memory usage of the current process.
    """
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / unit


def used_memory_readable() -> str:
    """
    Get the memory usage of the current process in a human-readable format.

    :return: Memory usage of the current process.
    """
    return get_readable_size(used_memory(1))


def profiling(func):
    """
    Create the Decorator to mark a function for profiling. The time and memory usage will be recorded and printed.

    Example:
    .. highlight:: python
    .. code-block:: python

        @profiling
        def foo():
            print(1)

    :param func: function to be profiled
    :return: arguments wrapper
    """
    from .predefined import default_logger

    @wraps(func)
    def arg_wrapper(*args, **kwargs):
        start_t = time.perf_counter()
        start_mem = used_memory(unit=1)
        r = func(*args, **kwargs)
        elapsed = time.perf_counter() - start_t
        end_mem = used_memory(unit=1)
        # level_prefix = ''.join('-' for v in inspect.stack() if v and v.index is not None and v.index >= 0)
        level_prefix = ''
        mem_status = f'memory Δ {get_readable_size(end_mem - start_mem)} {get_readable_size(start_mem)} -> {get_readable_size(end_mem)}'
        default_logger.info(
            f'{level_prefix} {func.__qualname__} time: {elapsed}s {mem_status}'
        )
        return r

    return arg_wrapper


class TimeDict:
    """Records of time information."""

    def __init__(self):
        self.accum_time = defaultdict(float)
        self.first_start_time = defaultdict(float)
        self.start_time = defaultdict(float)
        self.end_time = defaultdict(float)
        self._key_stack = []
        self._pending_reset = False

    def __enter__(self):
        _key = self._key_stack[-1]
        # store only the first enter time
        if _key not in self.first_start_time:
            self.first_start_time[_key] = time.perf_counter()
        self.start_time[_key] = time.perf_counter()
        return self

    def __exit__(self, typ, value, traceback):
        _key = self._key_stack.pop()
        self.end_time[_key] = time.perf_counter()
        self.accum_time[_key] += self.end_time[_key] - self.start_time[_key]
        if self._pending_reset:
            self.reset()

    def __call__(self, key: str, *args, **kwargs):
        """
        Add time counter.

        :param key: key name of the counter
        :param args: extra arguments
        :param kwargs: keyword arguments
        :return: self object
        """
        self._key_stack.append(key)
        return self

    def reset(self):
        """Clear the time information."""
        if self._key_stack:
            self._pending_reset = True
        else:
            self.accum_time.clear()
            self.start_time.clear()
            self.first_start_time.clear()
            self.end_time.clear()
            self._key_stack.clear()
            self._pending_reset = False

    def __str__(self):
        return ' '.join(f'{k}: {v:3.1f}s' for k, v in self.accum_time.items())


class TimeContext:
    """Timing a code snippet with a context manager."""

    time_attrs = ['years', 'months', 'days', 'hours', 'minutes', 'seconds']

    def __init__(self, task_name: str, logger: 'JinaLogger' = None):
        """
        Create the context manager to timing a code snippet.

        :param task_name: The context/message.
        :param logger: Use existing logger or use naive :func:`print`.

        Example:
        .. highlight:: python
        .. code-block:: python

            with TimeContext('loop'):
                do_busy()

        """
        self.task_name = task_name
        self._logger = logger
        self.duration = 0

    def __enter__(self):
        self.start = time.perf_counter()
        self._enter_msg()
        return self

    def _enter_msg(self):
        if self._logger:
            self._logger.info(self.task_name + '...')
        else:
            print(self.task_name, end=' ...\t', flush=True)

    def __exit__(self, typ, value, traceback):
        self.duration = self.now()

        self.readable_duration = get_readable_time(seconds=self.duration)

        self._exit_msg()

    def now(self) -> float:
        """
        Get the passed time from start to now.

        :return: passed time
        """
        return time.perf_counter() - self.start

    def _exit_msg(self):
        if self._logger:
            self._logger.info(
                f'{self.task_name} takes {self.readable_duration} ({self.duration:.2f}s)'
            )
        else:
            print(
                colored(
                    f'{self.task_name} takes {self.readable_duration} ({self.duration:.2f}s)'
                ),
                flush=True,
            )


class ProgressBar(TimeContext):
    """
    A simple progress bar.

    Example:
        .. highlight:: python
        .. code-block:: python

            with ProgressBar('loop'):
                do_busy()
    """

    col_width = 100
    clear_line = '\r{}\r'.format(' ' * col_width)

    def __init__(
        self,
        description: str = 'Working...',
        message_on_done: Union[str, Callable[..., str], None] = None,
    ):
        """
        Create the ProgressBar.

        :param description: The name of the task, will be displayed in front of the bar.
        :param message_on_done: The final message to print when the progress is complete
        """
        super().__init__(description, None)
        self._bars_on_row = 40
        self._completed_progress = 0
        self._last_rendered_progress = 0
        self._num_update_called = 0
        self._on_done = message_on_done

    def update(
        self,
        progress: float = 1.0,
        description: Optional[str] = None,
        message: Optional[str] = None,
        all_completed: bool = False,
        first_enter: bool = False,
    ) -> None:
        """
        Increment the progress bar by one unit.

        :param progress: The number of unit to increment.
        :param description: Change the description text before the progress bar on update.
        :param message: Change the message text followed after the progress bar on update.
        :param all_completed: Mark the task as fully completed.
        :param first_enter: if this method is called by `__enter__`
        """
        self._num_update_called += 0 if first_enter else 1
        self._completed_progress += progress
        if (
            abs(self._completed_progress - self._last_rendered_progress) < 0.5
            and not all_completed
        ):
            return
        self._last_rendered_progress = self._completed_progress
        sys.stdout.write(self.clear_line)
        elapsed = time.perf_counter() - self.start
        num_bars = self._completed_progress % self._bars_on_row
        num_bars = (
            self._bars_on_row
            if not num_bars and self._completed_progress
            else max(num_bars, 1)
        )
        num_fullbars = math.floor(num_bars)
        num_halfbars = 1 if (num_bars - num_fullbars <= 0.5) else 0

        bar_color = 'yellow' if all_completed else 'green'
        unfinished_bar_color = 'yellow' if all_completed else 'green'

        time_str = (
            '-:--:--'
            if first_enter
            else str(datetime.timedelta(seconds=elapsed)).split('.')[0]
        )
        speed_str = (
            'estimating...'
            if first_enter
            else f'{self._num_update_called / elapsed:3.1f} step/s'
        )

        description_str = description or self.task_name or ''
        msg_str = message or ''

        sys.stdout.write(
            '{:>10} {:<}{:<} {} {} {}'.format(
                description_str,
                colored('━' * num_fullbars, bar_color)
                + (colored('╸', bar_color if num_halfbars else unfinished_bar_color)),
                colored(
                    '━' * (self._bars_on_row - num_fullbars),
                    unfinished_bar_color,
                    attrs=['dark'],
                ),
                colored(time_str, 'cyan'),
                speed_str,
                msg_str,
            )
        )
        sys.stdout.flush()

    def _enter_msg(self):
        self.update(first_enter=True)

    def _exit_msg(self):
        if self._last_rendered_progress > 1:
            final_msg = f'\033[K{self._completed_progress:.0f} steps done in {self.readable_duration}'
            if self._on_done:
                if isinstance(self._on_done, str):
                    final_msg = self._on_done
                elif callable(self._on_done):
                    final_msg = self._on_done()
            self.update(0, all_completed=True)
            sys.stdout.write(final_msg)
            sys.stdout.write('\n')
        else:
            # no actual render happens
            sys.stdout.write(self.clear_line)
        sys.stdout.flush()
