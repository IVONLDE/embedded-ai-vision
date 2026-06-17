from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_main_window_keeps_theme_switching_out_of_global_header():
    qml = read_text("ui/main_windows.qml")

    assert "themeSelector" not in qml
    assert "Theme.setMode" not in qml
    assert "helpPopup.open()" not in qml


def test_each_function_view_has_local_question_mark_help():
    views = [
        "ui/views/DataManageView.qml",
        "ui/views/DataCleanView.qml",
        "ui/views/SampleGenView.qml",
        "ui/views/EvaluateView.qml",
        "ui/views/AlgoConfigView.qml",
        "ui/views/SystemSettingsView.qml",
    ]

    for view in views:
        qml = read_text(view)
        assert "HelpIcon" in qml, view

    help_icon = read_text("ui/HelpIcon.qml")
    assert 'text: "?"' in help_icon
    assert "Popup" in help_icon


def test_each_function_view_declares_frontend_display_data():
    expected_markers = {
        "ui/views/DataManageView.qml": ["demoDatasets", "loadDemoDatasets"],
        "ui/views/DataCleanView.qml": ["cleaningHistoryModel", "ListElement"],
        "ui/views/SampleGenView.qml": ["generationHistoryModel", "ListElement"],
        "ui/views/EvaluateView.qml": ["evalHistoryModel", "ListElement"],
        "ui/views/AlgoConfigView.qml": ["algoListModel", "ListElement"],
        "ui/views/SystemSettingsView.qml": ["settingsOverviewModel", "ListElement"],
    }

    for view, markers in expected_markers.items():
        qml = read_text(view)
        for marker in markers:
            assert marker in qml, f"{view} should expose frontend display data via {marker}"


def test_dataset_page_has_rich_mock_dataset_and_file_detail_data():
    qml = read_text("ui/views/DataManageView.qml")

    assert qml.count("sampleCount:") >= 8
    assert "demoFiles" in qml
    assert "dataset.demoFiles" in qml
    assert "SAR_Ship_20240519_0001.tif" in qml
    assert "UAV_INSPECTION_LOG_20240518_001.txt" in qml
    assert "SONAR_ECHO_20240517_0001.wav" in qml


def test_dataset_page_includes_empty_mock_datasets_for_ui_demonstration():
    qml = read_text("ui/views/DataManageView.qml")

    assert qml.count('sampleCount: 0') >= 3
    assert qml.count('size: "0 MB"') >= 3


def test_clean_and_generation_views_define_empty_source_dataset_fallbacks():
    fallback_markers = {
        "ui/views/DataCleanView.qml": [
            "var sources = []",
            "sources.push((item.name ||",
            "if (sources.length === 0) sources.push(",
            "root.sourceDatasets = sources",
        ],
        "ui/views/SampleGenView.qml": [
            "var sources = []",
            "sources.push((item.name ||",
            "if (sources.length === 0) sources.push(",
            "root.sourceDatasets = sources",
        ],
    }

    for view, markers in fallback_markers.items():
        qml = read_text(view)
        for marker in markers:
            assert marker in qml, f"{view} should keep the fallback source dataset flow via {marker}"

    assert "无可用源数据集" in read_text("ui/views/DataCleanView.qml")
    assert "无可用基础数据集" in read_text("ui/views/SampleGenView.qml")


def test_global_theme_singleton_defines_serious_light_theme_and_presets():
    theme = read_text("ui/Theme.qml")
    qmldir = read_text("ui/qmldir")

    assert "pragma Singleton" in theme
    assert 'property string mode: "light"' in theme
    assert 'readonly property color bg: mode === "light" ? "#F5F7FA"' in theme
    assert 'readonly property color primary: "#1D4ED8"' in theme
    assert "function setMode" in theme
    assert "singleton Theme 1.0 Theme.qml" in qmldir


def test_theme_switching_lives_in_system_settings_and_light_rows_are_not_dark():
    settings = read_text("ui/views/SystemSettingsView.qml")
    all_qml = "\n".join(
        read_text(path)
        for path in [
            "ui/views/DataManageView.qml",
            "ui/views/DataCleanView.qml",
            "ui/views/SampleGenView.qml",
            "ui/views/EvaluateView.qml",
            "ui/views/AlgoConfigView.qml",
            "ui/views/SystemSettingsView.qml",
        ]
    )

    assert "themeSelector" in settings
    assert "Theme.setMode" in settings
    for dark_literal in [
        "#1F2937",
        "#374151",
        "#454E5F",
        "#0B1120",
        "#131722",
        "#1A202C",
        "#1E2333",
        "#2D3748",
        "#3A4B6B",
    ]:
        assert dark_literal not in all_qml


def test_local_help_icons_are_offset_from_top_right_action_buttons():
    views = [
        "ui/views/DataManageView.qml",
        "ui/views/DataCleanView.qml",
        "ui/views/SampleGenView.qml",
        "ui/views/EvaluateView.qml",
        "ui/views/AlgoConfigView.qml",
        "ui/views/SystemSettingsView.qml",
    ]

    for view in views:
        qml = read_text(view)
        assert "anchors.topMargin: -16" in qml, view
        assert "anchors.rightMargin: -16" in qml, view


def test_algorithm_config_page_prioritizes_main_workspace_and_usage_guidance():
    qml = read_text("ui/views/AlgoConfigView.qml")

    assert 'import ".."' in qml
    assert "Layout.preferredWidth: 280" in qml
    assert "algorithmUsageText" in qml
    assert "docs/ALGORITHM_USAGE_GUIDE.md" in qml


def test_algorithm_usage_document_matches_backend_plugin_contract():
    doc = read_text("docs/ALGORITHM_USAGE_GUIDE.md")

    required_sections = [
        "# ISG 算法插件接入说明",
        "## 1. 文档定位",
        "## 2. 第一版支持范围",
        "## 3. 注册字段",
        "## 4. 插件函数签名",
        "## 5. 通用输入 payload",
        "## 6. 清洗算法输出",
        "## 7. 生成算法输出",
        "## 8. 评估算法输出",
        "## 10. 参数 schema",
    ]
    for section in required_sections:
        assert section in doc

    assert "def run(payload: dict, context) -> dict:" in doc
    assert "input_contract" in doc
    assert "output_contract" in doc
    assert '"category": "cleaning"' in doc
    assert "生成算法输出" in doc
