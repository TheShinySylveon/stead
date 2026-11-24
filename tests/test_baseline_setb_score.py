from ctx.metrics import run_baseline_and_setb_score


def test_baseline_setb_score():
    assert run_baseline_and_setb_score() == 0.85