"""test_workers.py — autodiscovery de plugins y que un worker procese algo de verdad."""

from workers.plugin_loader import discover_plugins


def test_discovers_the_three_core_plugins():
    plugins = discover_plugins()
    assert "fetch" in plugins
    assert "process" in plugins
    assert "notify" in plugins
    for name, info in plugins.items():
        assert "module_name" in info
        assert "timeout" in info


def test_notify_plugin_handles_a_task():
    from workers.plugins.notify import handle
    result = handle("test-task-id", {"webhook_url": None})
    assert result.get("notified") is True
