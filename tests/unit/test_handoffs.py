from agent.handoffs import RiskReport, FitReport

def test_risk_score_is_bounded():
    report = RiskReport(score=0.5, flags=[], explanation="sample")
    assert 0 <= report.score <= 1

def test_fit_score_is_bounded():
    report = FitReport(score=0.8)
    assert 0 <= report.score <= 1
