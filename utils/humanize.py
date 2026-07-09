# -*- coding: utf-8 -*-
import asyncio
import random


def _bounded_seconds(value: float, min_seconds: float = 0.1, max_seconds: float = 5.0) -> float:
    return max(min_seconds, min(float(value), max_seconds))


def jitter_seconds(base: float, ratio: float = 0.35, min_seconds: float = 0.1, max_seconds: float = 5.0) -> float:
    base = float(base)
    spread = abs(base * float(ratio))
    return _bounded_seconds(random.uniform(base - spread, base + spread), min_seconds, max_seconds)


async def human_delay(min_seconds: float = 0.3, max_seconds: float = 1.5) -> float:
    delay = random.uniform(_bounded_seconds(min_seconds), _bounded_seconds(max_seconds))
    await asyncio.sleep(delay)
    return delay


async def human_delay_ms(min_ms: int = 300, max_ms: int = 1500) -> float:
    return await human_delay(min_ms / 1000, max_ms / 1000)
