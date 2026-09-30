from log_analyzer import LogAnalyzer

def test_relevant_windows():
    analyzer = LogAnalyzer(context_lines=1)

    log = (
        "line1\n"
        "line2\n"
        "ERROR: CS0246 type or namespace not found\n"
        "line4\n"
        "line5"
    )

    windows = analyzer.relevant_windows(log)

    assert windows
    assert "CS0246" in windows[0]

def test_failed_tasks():
    analyzer = LogAnalyzer()

    timeline = {
        "records": [
            {
                "id": "1",
                "name": "Build",
                "result": "failed",
                "issues": [{"message": "CS0246 missing type"}],
                "log": {"id": 10},
            },
            {
                "id": "2",
                "name": "Checkout",
                "result": "succeeded",
            },
        ]
    }

    tasks = analyzer.failed_tasks(timeline)

    assert len(tasks) == 1
    assert tasks[0]["log_id"] == 10
