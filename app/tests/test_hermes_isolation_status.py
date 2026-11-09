import pytest

from hermes_process_manager import HermesProcessManager, IsolationBoundaryUnavailable


def test_isolation_status_keeps_launch_closed_without_product_proof():
    report = HermesProcessManager.inspect_isolation()
    assert report["status"] == "NOT_VERIFIED"
    assert report["backend"] == "UNAVAILABLE"
    assert report["launch_allowed"] is False
    assert report["code"] == "ISOLATION_PROOF_UNAVAILABLE"
    assert set(report["checks"]) == {"filesystem", "network_and_system_services", "resource_limits", "descendant_cleanup", "runtime_binding"}
    assert all(value == "NOT_VERIFIED" for value in report["checks"].values())
    with pytest.raises(IsolationBoundaryUnavailable) as denied:
        HermesProcessManager.require_isolation()
    assert denied.value.code == "ISOLATION_PROOF_UNAVAILABLE"
    assert denied.value.report["launch_allowed"] is False
    assert denied.value.report["checks"]["filesystem"] == "NOT_VERIFIED"
    with pytest.raises(TypeError):
        HermesProcessManager.require_isolation(report)
