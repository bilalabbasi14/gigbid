"""Blind panel statistics."""

from __future__ import annotations

import pytest

from evals.runners.blind_panel import fleiss_kappa, sign_test


def test_sign_test_is_two_sided() -> None:
    assert sign_test(5, 5) == 1.0
    assert sign_test(9, 1) == pytest.approx(0.0215, abs=1e-4)
    assert sign_test(0, 0) is None


def test_fleiss_kappa_perfect_and_chance() -> None:
    cats = ("a", "b", "tie")
    assert fleiss_kappa([["b", "b", "b"], ["a", "a", "a"], ["b", "b", "b"]], cats) == 1.0
    mixed = fleiss_kappa([["a", "b", "tie"], ["b", "a", "tie"], ["tie", "a", "b"]], cats)
    assert mixed is not None and mixed < 0
    assert fleiss_kappa([["a"], ["b"]], cats) is None
