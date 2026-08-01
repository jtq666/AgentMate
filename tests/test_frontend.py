from pathlib import Path

from streamlit.testing.v1 import AppTest

FRONTEND = Path(__file__).parents[1] / "agentmate" / "frontend"


def test_navigation_entry_renders_without_backend():
    app = AppTest.from_file(str(FRONTEND / "app.py"), default_timeout=15).run()
    assert not app.exception
    assert app.title[0].value == "研学工作台"


def test_all_page_scripts_fail_gracefully_without_backend():
    expected_titles = {
        "resources.py": "资料库",
        "assessment.py": "实践评测",
        "reports.py": "学习报告",
    }
    for filename, title in expected_titles.items():
        app = AppTest.from_file(str(FRONTEND / "app_pages" / filename), default_timeout=15).run()
        assert not app.exception
        assert app.title[0].value == title


def test_beginner_recommendation_button_fills_create_form():
    app = AppTest.from_file(
        str(FRONTEND / "app_pages" / "workbench.py"), default_timeout=15
    ).run()
    button = next(item for item in app.button if item.label == "一键填入推荐配置")
    app = button.click().run()
    values = {item.label: item.value for item in app.selectbox}
    assert values["我想学习"] == "ReAct"
    assert values["这次的目标"] == "准备面试"
    assert not app.exception
