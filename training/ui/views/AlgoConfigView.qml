import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."

Item {
    id: root
    anchors.fill: parent

    // ==========================================
    // 全局简洁主题规范
    // ==========================================
    readonly property color bgDark: Theme.bg
    readonly property color panelBg: Theme.panel
    readonly property color devAccentColor: Theme.primary
    readonly property color devAccentMuted: Theme.secondary

    readonly property color primaryColor: Theme.primary
    readonly property color textColor: Theme.text
    readonly property color textMuted: Theme.muted
    readonly property color borderColor: Theme.border
    readonly property color successColor: Theme.success
    readonly property color dangerColor: Theme.danger
    readonly property color tableHoverBg: Theme.hover
    readonly property color cleanTagColor: Theme.cleanTag
    readonly property color genTagColor: Theme.genTag

    HelpIcon {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.topMargin: -16
        anchors.rightMargin: -16
        title: "算法配置帮助"
        body: "本页用于查看、注册、修改和卸载算法插件，是生成、清洗、训练和评估算法的统一配置入口。\n\n1. 左侧按算法大类和数据模态分组展示插件，可通过顶部下拉框筛选全部、清洗、生成、评估或训练算法；点击分组可展开或折叠。\n2. 点击某个算法后，右侧会显示算法名称、所属类别、脚本或模块挂载路径、接口简述、使用说明和参数快照。\n3. “插件规范”按钮会弹出本项目的算法插件开发规范窗口，可下拉查看 run(payload, context) 入口、PARAMETERS 参数声明和输出格式。\n4. “注册新插件环境”用于接入新的 Python 插件。选择脚本后系统会自动反射 PARAMETERS，生成参数配置表；填写名称、类别、模态和说明后确认注册。\n5. “调参修改”用于修改已有算法的参数定义、名称、类别、模态、脚本路径或模块路径。内置模块算法会保留 module_path，脚本插件会复制并保存 script_path。\n6. 参数表支持新增、删除和编辑参数名、显示标签、类型、默认值、数值范围和下拉选项。保存后，数据生成/清洗/评估页面会按这些参数渲染动态配置控件。\n7. “卸载环境”会删除算法注册记录。删除前请确认没有正在运行的任务依赖该算法。\n8. 调整完成后建议回到对应业务页面刷新算法列表，确认新参数和新插件已经生效。"
    }

    // 状态控制
    property int pendingEditIndex: -1
    property int pendingDeleteIndex: -1

    // 分类折叠面板状态
    property int selectedAlgoId: -1
    property bool cleaningExpanded: true
    property bool generationExpanded: true
    property bool evaluationExpanded: true
    property bool trainingExpanded: true
    property int cleaningCount: 0
    property int generationCount: 0
    property int evaluationCount: 0
    property int trainingCount: 0
    property int totalAlgoCount: 0
    property string algoCategoryFilter: "全部算法"
    property string pluginSpecText: "<html><body style='font-family:Segoe UI,Microsoft YaHei,sans-serif;font-size:14px;color:" + root.textColor + ";background:transparent;padding:24px 30px;line-height:1.7'>" +
        "<h1 style='font-size:22px;color:" + root.primaryColor + ";margin:0 0 4px 0;font-weight:700'>ISG 算法插件开发规范</h1>" +
        "<p style='color:" + root.textMuted + ";margin:0 0 28px 0;font-size:13px'>Version 1.0 · Python 插件标准接口</p>" +

        "<h2 style='font-size:15px;color:" + root.primaryColor + ";margin:24px 0 8px 0'>概述</h2>" +
        "<p style='margin:0 0 12px 0'>ISG 算法插件是标准 Python <code style='background:" + root.tableHoverBg + ";padding:1px 6px;border-radius:3px'>.py</code> 文件，实现 <code style='background:" + root.tableHoverBg + ";padding:1px 6px;border-radius:3px'>run(payload, context)</code> 入口函数，声明模块级 <code style='background:" + root.tableHoverBg + ";padding:1px 6px;border-radius:3px'>PARAMETERS</code> 列表。</p>" +

        "<h2 style='font-size:15px;color:" + root.primaryColor + ";margin:24px 0 8px 0'>文件结构</h2>" +
        "<pre style='background:" + root.panelBg + ";color:" + root.textColor + ";border:1px solid " + root.borderColor + ";border-radius:6px;padding:14px 16px;font-family:Consolas,Courier New,monospace;font-size:12.5px;line-height:1.55;margin:0'># -*- coding: utf-8 -*-\n\"\"\"插件简要说明。\"\"\"\nfrom pathlib import Path\n\nPARAMETERS: list[dict[str, Any]] = [\n    {\n        \"name\": \"threshold\",\n        \"type\": \"float\",\n        \"label\": \"阈值\",\n        \"default\": 0.5,\n        \"min\": 0.0, \"max\": 1.0,\n        \"options\": [],\n        \"description\": \"判定阈值\",\n        \"required\": False,\n    },\n]\n\ndef run(payload: dict[str, Any], context: Any) -> dict[str, Any]:\n    \"\"\"算法入口。payload: parameters/input/output\n    成功: {\"ok\": True, \"outputs\": [...]}\n    失败: {\"ok\": False, \"error_code\": \"...\", \"message\": \"...\"}\"\"\"\n    ...</pre>" +

        "<h2 style='font-size:15px;color:" + root.primaryColor + ";margin:24px 0 8px 0'>PARAMETERS 字段</h2>" +
        "<table style='border-collapse:collapse;width:100%;font-size:13px'>" +
        "<tr style='border-bottom:2px solid " + root.primaryColor + "'><td style='padding:7px 10px;font-weight:700'>字段</td><td style='padding:7px 10px;font-weight:700'>类型</td><td style='padding:7px 10px;font-weight:700'>必填</td><td style='padding:7px 10px;font-weight:700'>说明</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:6px 10px'><code>name</code></td><td style='padding:6px 10px'>str</td><td style='padding:6px 10px'>是</td><td style='padding:6px 10px'>英文小写+下划线</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:6px 10px'><code>type</code></td><td style='padding:6px 10px'>str</td><td style='padding:6px 10px'>是</td><td style='padding:6px 10px'>string / int / float / bool / select</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:6px 10px'><code>label</code></td><td style='padding:6px 10px'>str</td><td style='padding:6px 10px'>是</td><td style='padding:6px 10px'>UI 中文名</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:6px 10px'><code>default</code></td><td style='padding:6px 10px'>*</td><td style='padding:6px 10px'>是</td><td style='padding:6px 10px'>默认值</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:6px 10px'><code>min / max</code></td><td style='padding:6px 10px'>float</td><td style='padding:6px 10px'>否</td><td style='padding:6px 10px'>数值范围</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:6px 10px'><code>options</code></td><td style='padding:6px 10px'>list</td><td style='padding:6px 10px'>否</td><td style='padding:6px 10px'>select 的候选项</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:6px 10px'><code>description</code></td><td style='padding:6px 10px'>str</td><td style='padding:6px 10px'>否</td><td style='padding:6px 10px'>说明文本</td></tr>" +
        "<tr><td style='padding:6px 10px'><code>required</code></td><td style='padding:6px 10px'>bool</td><td style='padding:6px 10px'>否</td><td style='padding:6px 10px'>默认 false</td></tr>" +
        "</table>" +

        "<h2 style='font-size:15px;color:" + root.primaryColor + ";margin:24px 0 8px 0'>类型约定</h2>" +
        "<table style='border-collapse:collapse;width:100%;font-size:13px'>" +
        "<tr style='border-bottom:2px solid " + root.primaryColor + "'><td style='padding:7px 10px;font-weight:700'>type</td><td style='padding:7px 10px;font-weight:700'>示例</td><td style='padding:7px 10px;font-weight:700'>说明</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:5px 10px'>string</td><td style='padding:5px 10px'><code>\"normal\"</code></td><td style='padding:5px 10px'>字符串</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:5px 10px'>int</td><td style='padding:5px 10px'><code>100</code></td><td style='padding:5px 10px'>整数</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:5px 10px'>float</td><td style='padding:5px 10px'><code>0.5</code></td><td style='padding:5px 10px'>浮点</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:5px 10px'>bool</td><td style='padding:5px 10px'><code>True / False</code></td><td style='padding:5px 10px'>布尔</td></tr>" +
        "<tr><td style='padding:5px 10px'>select</td><td style='padding:5px 10px'><code>\"A\"</code></td><td style='padding:5px 10px'>枚举，options 必填</td></tr>" +
        "</table>" +

        "<h2 style='font-size:15px;color:" + root.primaryColor + ";margin:24px 0 8px 0'>run() 函数</h2>" +
        "<p style='margin:0'>签名: <code style='background:" + root.tableHoverBg + ";padding:1px 6px;border-radius:3px'>def run(payload: dict, context: Any) -> dict</code></p>" +

        "<p style='font-weight:600;margin:14px 0 4px 0'>payload 结构</p>" +
        "<pre style='background:" + root.panelBg + ";color:" + root.textColor + ";border:1px solid " + root.borderColor + ";border-radius:6px;padding:12px 16px;font-family:Consolas,Courier New,monospace;font-size:12.5px;line-height:1.55;margin:0'>{\n  \"algorithm_key\": \"generation.image.geometric_transform\",\n  \"parameters\": { \"rotation_degrees\": 10.0 },\n  \"input\": {\n    \"dataset_id\": 1,\n    \"dataset_path\": \"/data/datasets/abc\",\n    \"samples\": [{ \"id\": 1, \"path\": \"...\", \"labels\": [...] }]\n  },\n  \"output\": { \"output_dir\": \"/data/tasks/42/output\" },\n  \"target_count\": 100\n}</pre>" +

        "<p style='font-weight:600;margin:14px 0 4px 0'>context 方法</p>" +
        "<table style='border-collapse:collapse;width:100%;font-size:13px'>" +
        "<tr style='border-bottom:2px solid " + root.primaryColor + "'><td style='padding:7px 10px;font-weight:700'>方法</td><td style='padding:7px 10px;font-weight:700'>说明</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:5px 10px;font-family:Consolas,monospace'>set_progress(percent, msg)</td><td style='padding:5px 10px'>更新进度 0–100</td></tr>" +
        "<tr style='border-bottom:1px solid " + root.borderColor + "'><td style='padding:5px 10px;font-family:Consolas,monospace'>log(level, msg, payload)</td><td style='padding:5px 10px'>记录日志 info/warn/error</td></tr>" +
        "<tr><td style='padding:5px 10px;font-family:Consolas,monospace'>is_cancel_requested() -> bool</td><td style='padding:5px 10px'>检查取消，周期性调用</td></tr>" +
        "</table>" +

        "<p style='font-weight:600;margin:14px 0 4px 0'>返回值</p>" +
        "<pre style='background:" + root.panelBg + ";color:" + root.textColor + ";border:1px solid " + root.borderColor + ";border-radius:6px;padding:12px 16px;font-family:Consolas,Courier New,monospace;font-size:12.5px;line-height:1.55;margin:0'>成功(生成): {\"ok\": True, \"outputs\": [{...}], \"logs\": []}\n成功(清洗): {\"ok\": True, \"suggestions\": [{...}], \"logs\": []}\n失败:      {\"ok\": False, \"error_code\": \"...\", \"message\": \"...\"}\n取消:      {\"ok\": False, \"error_code\": \"CANCELLED\", \"message\": \"...\"}</pre>" +

        "<h2 style='font-size:15px;color:" + root.primaryColor + ";margin:24px 0 8px 0'>命名约定</h2>" +
        "<p style='margin:0 0 2px 0'>· 参数 name: 英文小写+下划线 <code>blur_threshold</code></p>" +
        "<p style='margin:0 0 2px 0'>· 参数 label: 简短中文「模糊阈值」</p>" +
        "<p style='margin:0 0 2px 0'>· 算法 key: <code>.</code> 分隔 <code>generation.image.geo</code></p>" +
        "<p style='margin:0'>· 算法 name: UI 中文名「几何变换」</p>" +

        "<h2 style='font-size:15px;color:" + root.primaryColor + ";margin:24px 0 8px 0'>注意事项</h2>" +
        "<p style='margin:0 0 2px 0'>· PARAMETERS 必须模块级，无参数写 <code>PARAMETERS = []</code></p>" +
        "<p style='margin:0 0 2px 0'>· 不修改 PARAMETERS，IO 用 <code>pathlib.Path</code></p>" +
        "<p style='margin:0 0 2px 0'>· 耗时操作周期性检查 <code>context.is_cancel_requested()</code></p>" +
        "<p style='margin:0'>· 插件放 <code>plugins/user/</code> 或用 <code>module_path</code></p>" +

        "<p style='color:" + root.textMuted + ";font-size:12px;margin-top:30px'>📄 完整示例见 plugins/user/_TEMPLATE.py</p>" +
        "</body></html>"

    function findAlgoIndexById(algoId) {
        for (var i = 0; i < algoListModel.count; i++) {
            if (algoListModel.get(i).id === algoId) return i
        }
        return -1
    }

    readonly property int selectedAlgoIndex: root.findAlgoIndexById(root.selectedAlgoId)

    function selectedAlgoField(field) {
        var idx = root.selectedAlgoIndex
        if (idx === -1) return ""
        var d = algoListModel.get(idx)
        return d[field] !== undefined ? d[field] : ""
    }

    function showCategorySection(categoryLabel) {
        return root.algoCategoryFilter === "全部算法" || root.algoCategoryFilter === categoryLabel
    }

    function firstAlgoIdForCategory(categoryLabel) {
        for (var i = 0; i < algoListModel.count; i++) {
            var item = algoListModel.get(i)
            if (!item.isHeader && item.category === categoryLabel) return item.id
        }
        return -1
    }

    function applyAlgoCategoryFilter(categoryLabel) {
        root.algoCategoryFilter = categoryLabel || "全部算法"
        if (root.algoCategoryFilter === "全部算法") return

        if (root.algoCategoryFilter === "清洗算法") root.cleaningExpanded = true
        if (root.algoCategoryFilter === "生成算法") root.generationExpanded = true
        if (root.algoCategoryFilter === "评估算法") root.evaluationExpanded = true
        if (root.algoCategoryFilter === "训练算法") root.trainingExpanded = true

        if (root.selectedAlgoIndex !== -1 && root.selectedAlgoField("category") === root.algoCategoryFilter) return
        var firstId = root.firstAlgoIdForCategory(root.algoCategoryFilter)
        if (firstId !== -1) root.selectedAlgoId = firstId
    }

    // ================= 背景 =================
    Rectangle {
        anchors.fill: parent
        color: root.bgDark
        Canvas {
            anchors.fill: parent
            visible: Theme.mode === "dark"
            opacity: 0.02
            onPaint: {
                var ctx = getContext("2d");
                ctx.strokeStyle = root.devAccentColor;
                ctx.lineWidth = 1;
                for (var x = 0; x < width; x += 30) {
                    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
                }
                for (var y = 0; y < height; y += 30) {
                    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
                }
            }
        }
    }

    // ================= 数据模型 =================
    ListModel {
        id: algoListModel
    }

    ListModel { id: cleaningAlgoModel }
    ListModel { id: generationAlgoModel }
    ListModel { id: evaluationAlgoModel }
    ListModel { id: trainingAlgoModel }

    ListModel {
        id: editingParamsModel
    }

    ListModel { id: bindingEvalModel }

    function refreshBindingEvalCombo() {
        bindingEvalModel.clear()
        bindingEvalModel.append({key: "", display: "-- 未绑定 --"})
        for (var i = 0; i < algoListModel.count; i++) {
            var a = algoListModel.get(i)
            if (a.category === "评估算法") {
                bindingEvalModel.append({key: a.key, display: a.name})
            }
        }
        var boundKey = root.selectedAlgoField("boundEvalKey")
        for (var j = 0; j < bindingEvalModel.count; j++) {
            if (bindingEvalModel.get(j).key === boundKey) {
                bindingEvalCombo.currentIndex = j
                return
            }
        }
        bindingEvalCombo.currentIndex = 0
    }

    // 共享算法列表项委托
    Component {
        id: algoItemDelegate
        Rectangle {
            width: parent ? parent.width : 260
            height: model.isHeader ? 30 : 64
            radius: 0
            color: {
                if (model.isHeader) return Qt.rgba(29/255, 78/255, 216/255, 0.06)
                if (model.id === root.selectedAlgoId) return Qt.rgba(29/255, 78/255, 216/255, 0.10)
                if (itemMa.containsMouse) return root.tableHoverBg
                return "transparent"
            }
            border.color: model.id === root.selectedAlgoId ? root.devAccentColor : "transparent"
            border.width: 1

            MouseArea {
                id: itemMa
                anchors.fill: parent
                hoverEnabled: true
                enabled: !model.isHeader
                onClicked: { root.selectedAlgoId = model.id; root.refreshBindingEvalCombo() }
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: model.subCategory || model.name || ""
                color: root.devAccentColor
                font.pixelSize: 11
                font.bold: true
                visible: model.isHeader
            }

            RowLayout {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 12
                visible: !model.isHeader

                Rectangle {
                    width: 34; height: 34; radius: 5
                    color: root.bgDark
                    border.color: model.id === root.selectedAlgoId ? root.devAccentColor : root.borderColor
                    border.width: 1
                    Text {
                        text: {
                            var c = model.category
                            if (c === "清洗算法") return "清"
                            if (c === "生成算法") return "生"
                            if (c === "评估算法") return "评"
                            if (c === "训练算法") return "训"
                            return "?"
                        }
                        color: {
                            var c = model.category
                            if (c === "清洗算法") return root.cleanTagColor
                            if (c === "生成算法") return root.genTagColor
                            return root.devAccentColor
                        }
                        font.pixelSize: 14; font.bold: true; anchors.centerIn: parent
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text {
                        text: model.name
                        color: model.id === root.selectedAlgoId ? root.devAccentColor : root.textColor
                        font.pixelSize: 13; font.bold: true
                        elide: Text.ElideRight; Layout.fillWidth: true
                    }
                    Text {
                        text: model.subCategory
                        color: root.textMuted
                        font.pixelSize: 11
                    }
                }
            }
        }
    }

    // ================= 全局提示 Toast =================
    property string toastMessage: "✅ 操作成功"

    Popup {
        id: toastMsg
        modal: false
        closePolicy: Popup.NoAutoClose
        z: 2147483647
        x: Math.round((root.width - width) / 2)
        y: 40
        height: 40
        leftPadding: 20
        rightPadding: 20
        opacity: 0
        background: Rectangle { color: root.successColor; radius: 20 }
        contentItem: Text {
            id: toastText
            text: root.toastMessage
            color: "black"
            font.pixelSize: 14; font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        SequentialAnimation {
            id: toastAnim
            NumberAnimation { target: toastMsg; property: "opacity"; to: 1.0; duration: 300 }
        }
    }

    Timer {
        id: toastCloseTimer
        interval: 2300
        onTriggered: {
            toastMsg.opacity = 0
            toastMsg.close()
        }
    }

    Component.onDestruction: {
        toastCloseTimer.stop()
    }

    function showToast(msg) {
        root.toastMessage = msg
        toastMsg.open()
        toastAnim.restart()
        toastCloseTimer.restart()
    }

    Popup {
        id: pluginSpecPopup
        modal: true
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        width: Math.min(root.width - 80, 860)
        height: Math.min(root.height - 80, 680)
        padding: 0
        background: Item {
            // 柔和阴影层
            Rectangle {
                anchors.fill: parent; anchors.margins: 3; radius: 14
                color: Qt.rgba(0, 0, 0, 0.15)
            }
            Rectangle {
                anchors.fill: parent; anchors.margins: 1; radius: 12
                color: root.panelBg; border.color: root.borderColor; border.width: 1
            }
        }
        contentItem: ColumnLayout {
            spacing: 0

            // 标题栏 (右上角 扩大/关闭)
            Rectangle {
                Layout.fillWidth: true; height: 44
                color: "transparent"
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 20; anchors.rightMargin: 8
                    Text { text: "📋 插件规范"; color: root.textColor; font.pixelSize: 14; font.bold: true; Layout.fillWidth: true }
                    Rectangle { id: expandIcon; width: 28; height: 28; radius: 6
                        color: expandMa.containsMouse ? root.tableHoverBg : "transparent"
                        property bool isMax: false
                        Text { text: expandIcon.isMax ? "🗗" : "🗖"; color: root.textMuted; font.pixelSize: 14; anchors.centerIn: parent }
                        MouseArea { id: expandMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                expandIcon.isMax = !expandIcon.isMax
                                if (expandIcon.isMax) { pluginSpecPopup.width = root.width - 40; pluginSpecPopup.height = root.height - 40 }
                                else { pluginSpecPopup.width = Math.min(root.width - 80, 860); pluginSpecPopup.height = Math.min(root.height - 80, 680) }
                            }
                        }
                    }
                    Rectangle { id: closeIcon; width: 28; height: 28; radius: 6
                        color: closeMa.containsMouse ? Qt.rgba(245,63,63,0.1) : "transparent"
                        Text { text: "✕"; color: closeMa.containsMouse ? root.dangerColor : root.textMuted; font.pixelSize: 14; anchors.centerIn: parent }
                        MouseArea { id: closeMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: pluginSpecPopup.close()
                        }
                    }
                }
            }
            // 内容区
            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true; contentWidth: width; contentHeight: specText.implicitHeight + 24
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                Text { id: specText; width: parent.width; text: root.pluginSpecText; textFormat: Text.RichText; wrapMode: Text.WordWrap; padding: 18 }
            }

            // 底部栏 (右下角 下载PDF)
            Rectangle {
                Layout.fillWidth: true; height: 40
                color: "transparent"
                RowLayout { anchors.fill: parent; anchors.rightMargin: 12
                    Item { Layout.fillWidth: true }
                    Rectangle { id: downloadBtn; width: 90; height: 26; radius: 13
                        color: downloadMa.containsMouse ? root.primaryColor : root.tableHoverBg
                        Text { text: "⬇ 下载PDF"; color: downloadMa.containsMouse ? "white" : root.textColor; font.pixelSize: 11; anchors.centerIn: parent }
                        MouseArea { id: downloadMa; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { pluginSpecSaveDialog.selectedFile = "ISG 算法插件开发规范.pdf"; pluginSpecSaveDialog.open() }
                        }
                    }
                }
            }
        }
    }

    function categoryLabel(category) {
        if (category === "cleaning") return "清洗算法"
        if (category === "generation") return "生成算法"
        if (category === "evaluation") return "评估算法"
        if (category === "training") return "训练算法"
        return category || "未分类"
    }

    function categoryValue(label) {
        if (label === "清洗算法") return "cleaning"
        if (label === "生成算法") return "generation"
        if (label === "评估算法") return "evaluation"
        if (label === "训练算法") return "training"
        return label || "generation"
    }

    function scenarioKeyFromName(name) {
        if (name === "水下目标检测与识别") return "underwater_target_detection_recognition"
        if (name === "舰船目标识别与跟踪") return "ship_target_recognition_tracking"
        if (name === "系统健康状态预估与故障诊断") return "system_health_fault_diagnosis"
        if (name === "智能决策与指挥控制") return "intelligent_decision_command_control"
        if (name === "多模态数据融合") return "multimodal_data_fusion"
        return ""
    }

    function scenarioNameFromKey(key) {
        if (key === "underwater_target_detection_recognition") return "水下目标检测与识别"
        if (key === "ship_target_recognition_tracking") return "舰船目标识别与跟踪"
        if (key === "system_health_fault_diagnosis") return "系统健康状态预估与故障诊断"
        if (key === "intelligent_decision_command_control") return "智能决策与指挥控制"
        if (key === "multimodal_data_fusion") return "多模态数据融合"
        return key || "未指定场景"
    }

    function modalityFromSubCategory(text) {
        if (text.indexOf("文本") !== -1) return "text"
        if (text.indexOf("音频") !== -1) return "audio"
        if (text.indexOf("表格") !== -1 || text.indexOf("时序") !== -1) return "tabular"
        if (text.indexOf("视频") !== -1) return "video"
        if (text.indexOf("多模态") !== -1) return "multimodal"
        return "image"
    }

    function subtypeLabel(category, modality) {
        if (category === "cleaning") {
            if (modality === "text") return "文本清洗策略"
            if (modality === "audio") return "音频清洗策略"
            if (modality === "tabular") return "表格数据清洗"
            return "图像清洗策略"
        }
        if (category === "generation") {
            if (modality === "text") return "文本增强方法"
            if (modality === "audio") return "音频增强方法"
            if (modality === "multimodal") return "多模态增强方法"
            return "图像增强方法"
        }
        if (category === "training") {
            if (modality === "text") return "文本训练模型"
            if (modality === "audio") return "音频训练模型"
            if (modality === "tabular") return "时序训练模型"
            if (modality === "multimodal") return "多模态训练模型"
            return "图像训练模型"
        }
        if (category === "evaluation") {
            if (modality === "text") return "文本评估方法"
            if (modality === "audio") return "音频评估方法"
            if (modality === "tabular") return "时序评估方法"
            if (modality === "multimodal") return "多模态评估方法"
            return "图像评估方法"
        }
        return "未分类"
    }

    function modalityOrder(modality) {
        if (modality === "image") return 0
        if (modality === "audio") return 1
        if (modality === "text") return 2
        if (modality === "tabular") return 3
        if (modality === "video") return 4
        return 5
    }

    function categoryOrder(category) {
        if (category === "cleaning") return 0
        if (category === "generation") return 1
        if (category === "evaluation") return 2
        if (category === "training") return 3
        return 4
    }

    function isUserPlugin(item) {
        var script = String(item.script_path || "")
        return script !== ""
    }

    function normalizeParamType(typeName) {
        var t = String(typeName || "string")
        if (t === "number") return "float"
        if (t === "integer") return "int"
        return t
    }

    function isScriptPath(value) {
        var path = String(value || "")
        return path.toLowerCase().indexOf(".py") !== -1 || path.indexOf("/") !== -1 || path.indexOf("\\") !== -1
    }

    function compareAlgorithms(a, b) {
        var ac = root.categoryOrder(a.category)
        var bc = root.categoryOrder(b.category)
        if (ac !== bc) return ac - bc

        if (a.category === "training" && b.category === "training") {
            var av = a.validation_rules || {}
            var bv = b.validation_rules || {}
            var as = av["scenario_key"] || ""
            var bs = bv["scenario_key"] || ""
            if (as !== bs) return String(as).localeCompare(String(bs))
        }

        var am = root.modalityOrder(a.modality)
        var bm = root.modalityOrder(b.modality)
        if (am !== bm) return am - bm

        var au = root.isUserPlugin(a) ? 0 : 1
        var bu = root.isUserPlugin(b) ? 0 : 1
        if (au !== bu) return au - bu

        return String(a.name || "").localeCompare(String(b.name || ""), "zh-Hans-CN")
    }

    function appendGroupedEntry(model, entry, lastSubCategory) {
        if (lastSubCategory !== entry.subCategory) {
            model.append({
                isHeader: true,
                id: -1,
                name: entry.subCategory,
                category: entry.category,
                subCategory: entry.subCategory,
                modality: entry.modality,
                script: "",
                desc: "",
                paramsJson: "[]",
                enabled: false
            })
        }
        model.append(entry)
        return entry.subCategory
    }

    function loadAlgorithms() {
        backendService.getAlgorithms("", "")
    }

    function buildAlgorithmPayload(paramsJson) {
        var subCatStr = inputSubCategory.editText.trim() !== "" ? inputSubCategory.editText : inputSubCategory.currentText
        var category = root.categoryValue(inputCategory.currentText)
        var modality = root.modalityFromSubCategory(subCatStr)
        var rawParams = JSON.parse(paramsJson || "[]")
        var params = []
        for (var i = 0; i < rawParams.length; i++) {
            var p = rawParams[i]
            var ptype = p.type || "string"
            var paramDef = {
                name: p.n,
                label: p.label || p.n,
                type: ptype,
                required: false,
                default_value: p.v,
                description: p.desc || ""
            }
            if (ptype === "int" || ptype === "float") {
                paramDef.min_value = p.min !== undefined && p.min !== "" ? parseFloat(p.min) : null
                paramDef.max_value = p.max !== undefined && p.max !== "" ? parseFloat(p.max) : null
            }
            if (ptype === "select" && p.options) {
                if (Array.isArray(p.options)) {
                    paramDef.options = p.options
                } else {
                    paramDef.options = String(p.options).split(",").map(function(s) { return s.trim() }).filter(function(s) { return s !== "" })
                }
            }
            params.push(paramDef)
        }
        return {
            key: inputAlgoName.text.trim().replace(/\s+/g, "_").toLowerCase(),
            name: inputAlgoName.text.trim(),
            category: category,
            modality: modality,
            entry_type: "python_function",
            callable_name: "run",
            description: inputDesc.text,
            input_contract: {"dataset_required": true, "sample_required": true},
            output_contract: category === "cleaning" ? {"produces": ["suggestions"], "artifact_types": []}
                          : category === "training" ? {"produces": ["model_checkpoint"], "artifact_types": ["checkpoint"]}
                          : category === "evaluation" ? {"produces": ["metrics", "artifacts"], "artifact_types": ["report"]}
                          : {"produces": ["outputs"], "artifact_types": []},
            validation_rules: category === "training" ? {scenario_key: root.scenarioKeyFromName(subCatStr)} : {},
            parameters: params,
            modality: category === "training" ? "multimodal" : modality
        }
    }

    Component.onCompleted: root.loadAlgorithms()
    onVisibleChanged: { if (visible) root.loadAlgorithms() }
    onSelectedAlgoIdChanged: root.refreshBindingEvalCombo()

    Connections {
        target: backendService
        function onAlgorithmsUpdated(items) {
            if (!root.visible) return  // 只在当前页面可见时处理
            algoListModel.clear()
            cleaningAlgoModel.clear()
            generationAlgoModel.clear()
            evaluationAlgoModel.clear()
            trainingAlgoModel.clear()
            var cCount = 0, gCount = 0, eCount = 0, tCount = 0
            var sortedItems = (items || []).slice().sort(root.compareAlgorithms)
            var lastCleaningSub = ""
            var lastGenerationSub = ""
            var lastEvaluationSub = ""
            var lastTrainingSub = ""
            for (var i = 0; i < sortedItems.length; i++) {
                var item = sortedItems[i]
                var params = []
                var sourceParams = item.parameters || []
                for (var p = 0; p < sourceParams.length; p++) {
                    var sp = sourceParams[p]
                    params.push({
                        "n": sp.name || "",
                        "label": sp.label || sp.name || "",
                        "v": String(sp.default_value !== undefined ? sp.default_value : ""),
                        "type": root.normalizeParamType(sp.type),
                        "min": String(sp.min_value !== undefined && sp.min_value !== null ? sp.min_value : ""),
                        "max": String(sp.max_value !== undefined && sp.max_value !== null ? sp.max_value : ""),
                        "options": sp.options || [],
                        "desc": sp.description || ""
                    })
                }
                var subCat = root.subtypeLabel(item.category, item.modality)
                if (item.category === "training") {
                    var vr = item.validation_rules || {}
                    var scKey = vr["scenario_key"] || ""
                    if (scKey) subCat = "场景: " + root.scenarioNameFromKey(scKey)
                }
                var entry = {
                    id: item.id,
                    key: item.key,
                    name: item.name,
                    category: root.categoryLabel(item.category),
                    subCategory: subCat,
                    modality: item.modality,
                    script: item.script_path || item.module_path || "",
                    scriptPath: item.script_path || "",
                    modulePath: item.module_path || "",
                    desc: item.description || "",
                    paramsJson: JSON.stringify(params),
                    enabled: item.status === "enabled",
                    isHeader: false,
                    scenarioKey: (item.category === "training" ? ((item.validation_rules || {}).scenario_key || "") : ""),
                    boundEvalKey: item.bound_evaluation_key || "",
                    boundEvalName: item.bound_evaluation_name || ""
                }
                algoListModel.append(entry)
                if (item.category === "cleaning") {
                    lastCleaningSub = root.appendGroupedEntry(cleaningAlgoModel, entry, lastCleaningSub)
                    cCount++
                } else if (item.category === "generation") {
                    lastGenerationSub = root.appendGroupedEntry(generationAlgoModel, entry, lastGenerationSub)
                    gCount++
                } else if (item.category === "evaluation") {
                    lastEvaluationSub = root.appendGroupedEntry(evaluationAlgoModel, entry, lastEvaluationSub)
                    eCount++
                } else {
                    lastTrainingSub = root.appendGroupedEntry(trainingAlgoModel, entry, lastTrainingSub)
                    tCount++
                }
            }
            root.cleaningCount = cCount
            root.generationCount = gCount
            root.evaluationCount = eCount
            root.trainingCount = tCount
            root.totalAlgoCount = items.length
            if (sortedItems.length > 0 && root.selectedAlgoId === -1) {
                root.selectedAlgoId = sortedItems[0].id
            }
        }
    }

    function algorithmUsageText(category) {
        if (root.selectedAlgoIndex === -1) {
            return "选择算法后可查看使用说明。完整文档: docs/ALGORITHM_USAGE_GUIDE.md"
        }
        if (category === "清洗算法") {
            return "清洗算法用于发现重复、低质、异常或需脱敏的样本。输入为数据集样本路径和参数字典，输出为清洗建议、置信度和可选处理结果。上线前需确认参数默认值、输出建议类型和失败日志。"
        }
        return "生成算法用于对图像、音频或文本样本做扩增。输入为源样本路径、输出目录和参数字典，输出为新增样本文件及增强元数据。上线前需确认生成数量、输出格式、资源占用和可复现实验参数。"
    }

    // ================= 弹窗：文件选择器 =================
    FileDialog {
        id: scriptFileDialog
        title: "选择算法脚本/程序文件"
        nameFilters: ["Python 脚本 (*.py)"]
        onAccepted: {
            var path = selectedFile.toString()
            var cleanPath = decodeURIComponent(path.replace(/^(file:\/{2,3})/, ""))
            inputScriptPath.text = cleanPath
            var result = backendService.reflectParameters(cleanPath)
            if (result && result.ok) {
                editingParamsModel.clear()
                var params = result.parameters || []
                for (var i = 0; i < params.length; i++) {
                    var p = params[i]
                    editingParamsModel.append({
                        "n": p.name || "",
                        "label": p.label || p.name || "",
                        "v": String(p.default !== undefined ? p.default : ""),
                        "type": root.normalizeParamType(p.type),
                        "min": String(p.min !== undefined && p.min !== null ? p.min : ""),
                        "max": String(p.max !== undefined && p.max !== null ? p.max : ""),
                        "options": p.options || [],
                        "desc": p.description || ""
                    })
                }
                root.showToast("✅ 已自动加载 " + params.length + " 个参数")
            } else {
                root.showToast("⚠️ 参数反射失败: " + ((result && (result.error || result.message)) ? (result.error || result.message) : "未知错误"))
            }
        }
    }

    // ================= 弹窗：插件规范 PDF 保存 =================
    FileDialog {
        id: pluginSpecSaveDialog
        title: "保存插件规范 PDF"
        fileMode: FileDialog.SaveFile
        nameFilters: ["PDF 文档 (*.pdf)"]
        onAccepted: {
            var path = selectedFile.toString()
            var cleanPath = decodeURIComponent(path.replace(/^(file:\/{2,3})/, ""))
            var result = backendService.downloadAlgorithmPluginSpec(cleanPath)
            if (result && result.status === "success") root.showToast("✅ 插件规范已下载")
            else root.showToast("⚠️ " + ((result && result.message) ? result.message : "插件规范下载失败"))
        }
    }

    // ================= 弹窗：二次确认删除 =================
    Popup {
        id: deleteConfirmPopup
        width: 320
        height: 190
        modal: true
        focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            color: root.panelBg
            radius: 8
            border.color: root.dangerColor
            border.width: 1
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 15

            RowLayout {
                spacing: 10
                Text { text: "⚠️"; font.pixelSize: 20 }
                Text { text: "确认卸载此算法吗？"; color: root.textColor; font.pixelSize: 15; font.bold: true }
            }

            Text {
                text: "卸载后，清洗或生成模块将无法再调用此自定义算法。"
                color: root.textMuted
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                spacing: 15
                Item { Layout.fillWidth: true }
                Button {
                    text: "取消"
                    Layout.preferredWidth: 80
                    Layout.preferredHeight: 30
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: deleteConfirmPopup.close()
                }
                Button {
                    text: "确认卸载"
                    Layout.preferredWidth: 80
                    Layout.preferredHeight: 30
                    background: Rectangle { color: root.dangerColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: "black"; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        if (root.pendingDeleteIndex !== -1) {
                            var result = backendService.deleteAlgorithm(algoListModel.get(root.pendingDeleteIndex).id)
                            if (result && result.ok) {
                                root.selectedAlgoId = -1
                                root.loadAlgorithms()
                                root.showToast("🗑️ 算法已成功卸载")
                            } else {
                                root.showToast("⚠️ 算法卸载失败")
                            }
                        }
                        deleteConfirmPopup.close()
                    }
                }
            }
        }
    }

    // ================= 核心弹窗：配置新算法/修改算法 =================
    Popup {
        id: algoConfigPopup
        width: 800
        height: 600
        modal: true
        focus: true
        x: Math.round((root.width - width) / 2)
        y: Math.round((root.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.NoAutoClose
        background: Rectangle {
            color: root.panelBg
            radius: 8
            border.color: root.devAccentMuted
            border.width: 1
            Rectangle { anchors.fill: parent; color: root.devAccentColor; opacity: 0.02; radius: 8 }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 25
            spacing: 20

            // 标题栏
            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: root.pendingEditIndex === -1 ? "🧩 接入自定义新插件" : "⚙️ 修改插件底层配置"
                    color: root.devAccentColor
                    font.pixelSize: 18
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    width: 30; height: 30; color: "transparent"; radius: 4
                    Text { text: "✕"; color: root.textMuted; font.pixelSize: 18; anchors.centerIn: parent }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor; hoverEnabled: true
                        onEntered: { parent.color = root.tableHoverBg }
                        onExited: { parent.color = "transparent" }
                        onClicked: algoConfigPopup.close()
                    }
                }
            }

            Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor }

            // 左右分栏：左侧基础信息，右侧动态参数配置
            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 30

                // === 左栏：基础信息 ===
                ColumnLayout {
                    Layout.preferredWidth: 320
                    Layout.fillHeight: true
                    spacing: 15

                    Text { text: "📝 基础映射信息"; color: root.textColor; font.pixelSize: 14; font.bold: true }

                    ColumnLayout {
                        spacing: 6; Layout.fillWidth: true
                        Text { text: "插件名称:"; color: root.textMuted; font.pixelSize: 12 }
                        Rectangle {
                            Layout.fillWidth: true; height: 36; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                            TextInput { id: inputAlgoName; color: root.textColor; font.pixelSize: 13; anchors.fill: parent; leftPadding: 10; verticalAlignment: TextInput.AlignVCenter }
                        }
                    }

                    ColumnLayout {
                        spacing: 6; Layout.fillWidth: true
                        Text {
                            text: inputCategory.currentIndex === 2 ? "所属应用场景:" : "细分策略类别 (可直接输入新增):"
                            color: root.textMuted; font.pixelSize: 12
                        }
                        ComboBox {
                            id: inputCategory
                            model: ["清洗算法", "生成算法", "训练算法", "评估算法"]
                            Layout.fillWidth: true; Layout.preferredHeight: 36
                            background: Rectangle { color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 4 }
                            contentItem: Text { text: inputCategory.currentText; color: root.textColor; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; leftPadding: 10 }
                            popup: Popup {
                                y: inputCategory.height + 2; width: inputCategory.width; padding: 4
                                background: Rectangle { color: root.panelBg; border.color: root.borderColor; radius: 6 }
                                contentItem: ListView {
                                    clip: true; implicitHeight: contentHeight
                                    model: inputCategory.delegateModel
                                }
                            }
                            delegate: ItemDelegate {
                                width: inputCategory.width - 8; height: 32
                                contentItem: Text { text: modelData; color: root.textColor; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; leftPadding: 10 }
                                background: Rectangle { color: hovered ? root.tableHoverBg : "transparent"; radius: 4 }
                            }
                        }
                    }

                    ColumnLayout {
                        spacing: 6; Layout.fillWidth: true
                        ComboBox {
                            id: inputSubCategory
                            editable: inputCategory.currentIndex !== 2
                            model: {
                                if (inputCategory.currentIndex === 0) return ["图像清洗策略", "文本清洗策略", "音频清洗策略", "表格数据清洗"]
                                if (inputCategory.currentIndex === 1) return ["图像增强方法", "文本增强方法", "音频增强方法", "多模态增强方法", "深度学习生成"]
                                if (inputCategory.currentIndex === 2) return ["水下目标检测与识别", "舰船目标识别与跟踪", "系统健康状态预估与故障诊断", "智能决策与指挥控制", "多模态数据融合"]
                                if (inputCategory.currentIndex === 3) return ["多模态评估方法"]
                                return []
                            }
                            Layout.fillWidth: true; Layout.preferredHeight: 36
                            background: Rectangle { color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 4 }
                            contentItem: TextInput {
                                leftPadding: 10; rightPadding: 30; text: inputSubCategory.editText
                                color: root.textColor; font.pixelSize: 13; verticalAlignment: TextInput.AlignVCenter
                                onTextChanged: inputSubCategory.editText = text
                            }
                        }
                    }

                    ColumnLayout {
                        spacing: 6; Layout.fillWidth: true
                        Text { text: "挂载脚本/程序物理路径:"; color: root.textMuted; font.pixelSize: 12 }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8
                            Rectangle {
                                Layout.fillWidth: true; height: 36; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                                TextInput { id: inputScriptPath; color: root.devAccentColor; font.pixelSize: 13; font.family: "Courier"; anchors.fill: parent; leftPadding: 10; verticalAlignment: TextInput.AlignVCenter; clip: true }
                            }
                            Button {
                                text: "浏览..."; Layout.preferredHeight: 36; Layout.preferredWidth: 60
                                background: Rectangle { color: root.tableHoverBg; border.color: root.borderColor; border.width: 1; radius: 4 }
                                contentItem: Text { text: parent.text; color: root.textColor; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                onClicked: scriptFileDialog.open()
                            }
                        }
                    }

                    ColumnLayout {
                        spacing: 6; Layout.fillWidth: true
                        Text { text: "底层功能简述:"; color: root.textMuted; font.pixelSize: 12 }
                        Rectangle {
                            Layout.fillWidth: true; Layout.preferredHeight: 60; color: root.bgDark; radius: 4; border.color: root.borderColor; border.width: 1
                            TextEdit { id: inputDesc; color: root.textColor; font.pixelSize: 13; anchors.fill: parent; padding: 10; wrapMode: TextEdit.Wrap }
                        }
                    }

                    Item { Layout.fillHeight: true }
                }

                Rectangle { Layout.fillHeight: true; width: 1; color: root.borderColor }

                // === 右栏：动态参数配置引擎 ===
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 15

                    RowLayout {
                        Layout.fillWidth: true
                        Text { text: "⚙️ 动态反射参数列表"; color: root.textColor; font.pixelSize: 14; font.bold: true }
                        Item { Layout.fillWidth: true }
                        Text { text: "这些参数将在功能面板中动态生成输入框"; color: root.textMuted; font.pixelSize: 11 }
                    }

                    // 参数列表视图
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        color: root.bgDark
                        border.color: root.borderColor
                        border.width: 1
                        radius: 6
                        clip: true

                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 0

                            Rectangle {
                                Layout.fillWidth: true; height: 36; color: Theme.rowAlt
                                Rectangle { width: parent.width; height: 1; color: root.borderColor; anchors.bottom: parent.bottom }
                                RowLayout {
                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10; spacing: 6
                                    Text { text: "参数名"; color: root.textMuted; font.pixelSize: 11; font.bold: true; Layout.fillWidth: true }
                                    Text { text: "标签"; color: root.textMuted; font.pixelSize: 11; font.bold: true; Layout.fillWidth: true }
                                    Text { text: "类型"; color: root.textMuted; font.pixelSize: 11; font.bold: true; Layout.preferredWidth: 70 }
                                    Text { text: "操作"; color: root.textMuted; font.pixelSize: 11; font.bold: true; Layout.preferredWidth: 32; horizontalAlignment: Text.AlignHCenter }
                                }
                            }

                            ListView {
                                id: paramListView
                                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                                model: editingParamsModel

                                Text {
                                    visible: editingParamsModel.count === 0
                                    text: "此插件无动态参数配置"
                                    color: root.textMuted; font.pixelSize: 12; anchors.centerIn: parent
                                }

                                delegate: Rectangle {
                                    width: paramListView.width
                                    height: (root.normalizeParamType(model.type) === "int" || root.normalizeParamType(model.type) === "float" || root.normalizeParamType(model.type) === "select") ? 110 : 76
                                    color: index % 2 === 0 ? "transparent" : root.tableHoverBg

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 10
                                        spacing: 2

                                        // 第一行：参数名 + 标签 + 类型 + 默认值 + 删除
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 36
                                            spacing: 6
                                            // 参数名
                                            Rectangle {
                                                Layout.fillWidth: true; Layout.minimumWidth: 82; height: 28; color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 3
                                                TextInput {
                                                    text: model.n; color: root.textColor; font.pixelSize: 11; anchors.fill: parent; leftPadding: 5; rightPadding: 5; clip: true; verticalAlignment: TextInput.AlignVCenter
                                                    onTextChanged: editingParamsModel.setProperty(index, "n", text)
                                                }
                                            }
                                            // 显示标签
                                            Rectangle {
                                                Layout.fillWidth: true; Layout.minimumWidth: 82; height: 28; color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 3
                                                TextInput {
                                                    text: model.label; color: root.textColor; font.pixelSize: 11; anchors.fill: parent; leftPadding: 5; rightPadding: 5; clip: true; verticalAlignment: TextInput.AlignVCenter
                                                    onTextChanged: editingParamsModel.setProperty(index, "label", text)
                                                }
                                            }
                                            // 类型选择
                                            ComboBox {
                                                id: paramTypeCombo
                                                Layout.preferredWidth: 70; Layout.preferredHeight: 28
                                                model: ["string", "int", "float", "bool", "select"]
                                                currentIndex: {
                                                    var t = model.type || "string"
                                                    t = root.normalizeParamType(t)
                                                    if (t === "int") return 1
                                                    if (t === "float") return 2
                                                    if (t === "bool") return 3
                                                    if (t === "select") return 4
                                                    return 0
                                                }
                                                onCurrentTextChanged: editingParamsModel.setProperty(index, "type", currentText)
                                                background: Rectangle { color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 3 }
                                                contentItem: Text { text: paramTypeCombo.currentText; color: root.devAccentColor; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter; leftPadding: 5 }
                                                popup: Popup {
                                                    y: paramTypeCombo.height + 2; width: 90; padding: 3
                                                    background: Rectangle { color: root.panelBg; border.color: root.borderColor; radius: 5 }
                                                    contentItem: ListView { clip: true; implicitHeight: contentHeight; model: paramTypeCombo.delegateModel }
                                                }
                                                delegate: ItemDelegate {
                                                    width: 84; height: 24
                                                    contentItem: Text { text: modelData; color: root.textColor; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter; leftPadding: 6 }
                                                    background: Rectangle { color: hovered ? root.tableHoverBg : "transparent"; radius: 3 }
                                                }
                                            }
                                            // 默认值
                                            Rectangle {
                                                visible: false
                                                Layout.fillWidth: true; height: 28; color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 3
                                                TextInput {
                                                    text: model.v; color: root.devAccentColor; font.pixelSize: 11; anchors.fill: parent; leftPadding: 5; verticalAlignment: TextInput.AlignVCenter
                                                    onTextChanged: editingParamsModel.setProperty(index, "v", text)
                                                }
                                            }
                                            // 删除按钮
                                            Rectangle {
                                                Layout.preferredWidth: 26; height: 26; radius: 3
                                                color: delMa2.containsMouse ? root.dangerColor : "transparent"
                                                border.color: delMa2.containsMouse ? "transparent" : root.borderColor; border.width: 1
                                                Text { text: "✕"; font.pixelSize: 11; anchors.centerIn: parent; color: delMa2.containsMouse ? "white" : root.textMuted }
                                                MouseArea { id: delMa2; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: editingParamsModel.remove(index) }
                                            }
                                        }

                                        // 第二行：min/max (int/float) 或 options (select)
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 28
                                            spacing: 6
                                            Text {
                                                text: "默认值"; color: root.textMuted; font.pixelSize: 10
                                                Layout.preferredWidth: 44
                                            }
                                            Rectangle {
                                                Layout.fillWidth: true; height: 24; color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 3
                                                TextInput {
                                                    text: model.v; color: root.devAccentColor; font.pixelSize: 10; anchors.fill: parent; leftPadding: 5; rightPadding: 5; clip: true; verticalAlignment: TextInput.AlignVCenter
                                                    onTextChanged: editingParamsModel.setProperty(index, "v", text)
                                                }
                                            }
                                        }

                                        RowLayout {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 30
                                            visible: root.normalizeParamType(model.type) === "int" || root.normalizeParamType(model.type) === "float" || root.normalizeParamType(model.type) === "select"
                                            spacing: 6

                                            // int/float: min + max
                                            Text {
                                                visible: root.normalizeParamType(model.type) === "int" || root.normalizeParamType(model.type) === "float"
                                                text: "min"; color: root.textMuted; font.pixelSize: 10
                                                Layout.preferredWidth: 24
                                            }
                                            Rectangle {
                                                visible: root.normalizeParamType(model.type) === "int" || root.normalizeParamType(model.type) === "float"
                                                Layout.preferredWidth: 65; height: 24; color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 3
                                                TextInput {
                                                    text: model.min; color: root.textMuted; font.pixelSize: 10; anchors.fill: parent; leftPadding: 4; rightPadding: 4; clip: true; verticalAlignment: TextInput.AlignVCenter
                                                    onTextChanged: editingParamsModel.setProperty(index, "min", text)
                                                }
                                            }
                                            Text {
                                                visible: root.normalizeParamType(model.type) === "int" || root.normalizeParamType(model.type) === "float"
                                                text: "max"; color: root.textMuted; font.pixelSize: 10
                                                Layout.preferredWidth: 28
                                            }
                                            Rectangle {
                                                visible: root.normalizeParamType(model.type) === "int" || root.normalizeParamType(model.type) === "float"
                                                Layout.preferredWidth: 65; height: 24; color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 3
                                                TextInput {
                                                    text: model.max; color: root.textMuted; font.pixelSize: 10; anchors.fill: parent; leftPadding: 4; rightPadding: 4; clip: true; verticalAlignment: TextInput.AlignVCenter
                                                    onTextChanged: editingParamsModel.setProperty(index, "max", text)
                                                }
                                            }

                                            // select: options
                                            Text {
                                                visible: root.normalizeParamType(model.type) === "select"
                                                text: "选项"; color: root.textMuted; font.pixelSize: 10
                                                Layout.preferredWidth: 28
                                            }
                                            Rectangle {
                                                visible: root.normalizeParamType(model.type) === "select"
                                                Layout.fillWidth: true; height: 24; color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 3
                                                TextInput {
                                                    text: typeof model.options === "object" && model.options && model.options.length !== undefined ? model.options.join(",") : String(model.options || ""); color: root.textMuted; font.pixelSize: 10; anchors.fill: parent; leftPadding: 4; rightPadding: 4; clip: true; verticalAlignment: TextInput.AlignVCenter
                                                    onTextChanged: editingParamsModel.setProperty(index, "options", text.split(",").map(function(s) { return s.trim() }).filter(function(s) { return s !== "" }))
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            // 底部新增参数区
                            Rectangle {
                                Layout.fillWidth: true; height: 58; color: Theme.rowAlt
                                Rectangle { width: parent.width; height: 1; color: root.borderColor; anchors.top: parent.top }
                                RowLayout {
                                    anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 10; spacing: 6
                                    TextField {
                                        id: newParamName; Layout.preferredWidth: 80; Layout.preferredHeight: 28
                                        color: root.textColor; font.pixelSize: 11; leftPadding: 5; rightPadding: 5; verticalAlignment: TextInput.AlignVCenter; clip: true
                                        placeholderText: "参数名"; placeholderTextColor: root.textMuted
                                        background: Rectangle { color: root.panelBg; border.color: root.borderColor; border.width: 1; radius: 3 }
                                    }
                                    TextField {
                                        id: newParamLabel; Layout.preferredWidth: 80; Layout.preferredHeight: 28
                                        color: root.textColor; font.pixelSize: 11; leftPadding: 5; rightPadding: 5; verticalAlignment: TextInput.AlignVCenter; clip: true
                                        placeholderText: "标签"; placeholderTextColor: root.textMuted
                                        background: Rectangle { color: root.panelBg; border.color: root.borderColor; border.width: 1; radius: 3 }
                                    }
                                    ComboBox {
                                        id: newParamType; Layout.preferredWidth: 65; Layout.preferredHeight: 28
                                        model: ["string", "int", "float", "bool", "select"]
                                        currentIndex: 0
                                        background: Rectangle { color: root.panelBg; border.color: root.borderColor; border.width: 1; radius: 3 }
                                        contentItem: Text { text: newParamType.currentText; color: root.devAccentColor; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter; leftPadding: 5 }
                                        popup: Popup {
                                            y: newParamType.height + 2; width: 90; padding: 3
                                            background: Rectangle { color: root.panelBg; border.color: root.borderColor; radius: 5 }
                                            contentItem: ListView { clip: true; implicitHeight: contentHeight; model: newParamType.delegateModel }
                                        }
                                        delegate: ItemDelegate {
                                            width: 84; height: 24
                                            contentItem: Text { text: modelData; color: root.textColor; font.pixelSize: 11; verticalAlignment: Text.AlignVCenter; leftPadding: 6 }
                                            background: Rectangle { color: hovered ? root.tableHoverBg : "transparent"; radius: 3 }
                                        }
                                    }
                                    TextField {
                                        id: newParamVal; Layout.fillWidth: true; Layout.preferredHeight: 28
                                        color: root.devAccentColor; font.pixelSize: 11; leftPadding: 5; rightPadding: 5; verticalAlignment: TextInput.AlignVCenter; clip: true
                                        placeholderText: "默认值"; placeholderTextColor: root.textMuted
                                        background: Rectangle { color: root.panelBg; border.color: root.borderColor; border.width: 1; radius: 3 }
                                    }
                                    Button {
                                        text: "添加"; Layout.preferredWidth: 45; Layout.preferredHeight: 28
                                        background: Rectangle { color: root.devAccentMuted; radius: 3 }
                                        contentItem: Text { text: parent.text; color: "black"; font.pixelSize: 11; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                        onClicked: {
                                            if (newParamName.text.trim() !== "") {
                                                editingParamsModel.append({
                                                    "n": newParamName.text.trim(),
                                                    "label": newParamLabel.text.trim() || newParamName.text.trim(),
                                                    "v": newParamVal.text,
                                                    "type": newParamType.currentText,
                                                    "min": "",
                                                    "max": "",
                                                    "options": "",
                                                    "desc": ""
                                                })
                                                newParamName.text = ""; newParamLabel.text = ""; newParamVal.text = ""
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // 底部操作按钮
            RowLayout {
                Layout.fillWidth: true; spacing: 15
                Item { Layout.fillWidth: true }
                Button {
                    text: "取消"; Layout.preferredWidth: 90; Layout.preferredHeight: 36
                    background: Rectangle { color: "transparent"; border.color: root.borderColor; border.width: 1; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.textMuted; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: algoConfigPopup.close()
                }
                Button {
                    text: root.pendingEditIndex === -1 ? "确认注册" : "保存修改"
                    Layout.preferredWidth: 140; Layout.preferredHeight: 36
                    background: Rectangle { color: root.devAccentColor; radius: 4 }
                    contentItem: Text { text: parent.text; color: root.bgDark; font.bold: true; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: {
                        if (inputAlgoName.text.trim() === "" || inputScriptPath.text.trim() === "") {
                            root.showToast("⚠️ 插件名称和路径不能为空")
                            return
                        }
                        // 收集参数（含完整元数据）
                        var pArray = []
                        for(var i=0; i<editingParamsModel.count; i++) {
                            var m = editingParamsModel.get(i)
                            pArray.push({
                                "n": m.n, "label": m.label, "v": m.v, "type": m.type,
                                "min": m.min || "", "max": m.max || "",
                                "options": m.options || "", "desc": m.desc || ""
                            })
                        }
                        var pJsonStr = JSON.stringify(pArray)

                        var payload = root.buildAlgorithmPayload(pJsonStr)
                        var inputPath = inputScriptPath.text.trim()
                        var currentData = root.pendingEditIndex === -1 ? null : algoListModel.get(root.pendingEditIndex)
                        var isScriptPlugin = root.pendingEditIndex === -1 || root.isScriptPath(inputPath) || (currentData && currentData.scriptPath !== "")

                        if (isScriptPlugin) {
                            var importResult = backendService.importPluginFile(inputPath)
                            if (!importResult.ok) {
                                root.showToast("⚠️ 文件复制失败: " + (importResult.message || "未知错误"))
                                return
                            }
                            payload.script_path = importResult.path
                            payload.module_path = ""
                        } else {
                            payload.module_path = inputPath
                            payload.script_path = ""
                        }

                        var result = root.pendingEditIndex === -1
                            ? backendService.createAlgorithm(payload)
                            : backendService.updateAlgorithm(algoListModel.get(root.pendingEditIndex).id, payload)
                        if (root.pendingEditIndex === -1) {
                            if (result && result.ok) root.showToast("✅ 新插件引擎已接入")
                            else root.showToast("⚠️ 插件注册失败: " + ((result && result.message) ? result.message : "未知错误"))
                        } else {
                            if (result && result.ok) root.showToast("✅ 底层配置已更新")
                            else root.showToast("⚠️ 配置保存失败: " + ((result && result.message) ? result.message : "未知错误"))
                        }
                        if (result && result.ok) {
                            root.loadAlgorithms()
                            algoConfigPopup.close()
                        }
                    }
                }
            }
        }
    }


    // ========================================================================
    // ======================== 全新界面主体：Master-Detail 控制台 ================
    // ========================================================================
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 20

        // 顶栏栏：控制台 Header
        RowLayout {
            Layout.fillWidth: true
            spacing: 15

            Rectangle { width: 4; height: 24; color: root.devAccentColor; radius: 2 }

            Label {
                text: "算法引擎与二次插件控制台"
                font.pixelSize: 22
                font.bold: true
                color: root.textColor
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "插件规范"
                font.bold: true
                font.pixelSize: 14
                background: Rectangle {
                    color: parent.pressed ? "#1A00838F" : parent.hovered ? "#1A00E5FF" : "transparent"
                    border.color: root.devAccentColor
                    border.width: 1
                    radius: 4
                }
                contentItem: Text {
                    text: parent.text
                    color: root.devAccentColor
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: {
                    pluginSpecPopup.open()
                }
            }

            Button {
                text: "+ 注册新插件环境"
                font.bold: true
                font.pixelSize: 14
                background: Rectangle {
                    color: parent.pressed ? "#1A00838F" : parent.hovered ? "#1A00E5FF" : "transparent"
                    border.color: root.devAccentColor
                    border.width: 1
                    radius: 4
                }
                contentItem: Text {
                    text: parent.text
                    color: root.devAccentColor
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: {
                    root.pendingEditIndex = -1
                    inputAlgoName.text = ""
                    inputCategory.currentIndex = 0
                    inputSubCategory.editText = ""
                    inputScriptPath.text = ""
                    inputDesc.text = ""
                    editingParamsModel.clear()
                    algoConfigPopup.open()
                }
            }
        }

        // ================= Master-Detail 左右分栏核心 =================
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 20

            // ---------------- 左侧 (Master)：分类折叠算法列表 ----------------
            Rectangle {
                Layout.preferredWidth: 280
                Layout.fillHeight: true
                color: root.panelBg
                border.color: root.borderColor
                border.width: 1
                radius: 8
                clip: true

                Text {
                    anchors.centerIn: parent
                    text: "暂无自定义算法注册"
                    color: root.textMuted
                    font.pixelSize: 14
                    visible: algoListModel.count === 0
                }

                Flickable {
                    id: algoListFlickable
                    anchors.fill: parent
                    contentHeight: Math.max(sectionColumn.implicitHeight, 96 + root.totalAlgoCount * 68 + 200)
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    visible: algoListModel.count > 0

                    ScrollBar.vertical: ScrollBar {
                        policy: ScrollBar.AlwaysOn
                        interactive: true
                    }

                    ColumnLayout {
                        id: sectionColumn
                        width: parent.width - 12
                        spacing: 0

                        // ---- 统计概览 ----
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 96
                            color: Qt.rgba(29/255, 78/255, 216/255, 0.06)

                            ComboBox {
                                id: algoCategoryFilterCombo
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                anchors.topMargin: 10
                                height: 32
                                model: ["全部算法", "清洗算法", "生成算法", "评估算法", "训练算法"]
                                currentIndex: Math.max(0, model.indexOf(root.algoCategoryFilter))
                                background: Rectangle { color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 4 }
                                contentItem: Text { text: algoCategoryFilterCombo.currentText; color: root.textColor; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; leftPadding: 10 }
                                popup: Popup {
                                    y: algoCategoryFilterCombo.height + 2; width: algoCategoryFilterCombo.width; padding: 3
                                    background: Rectangle { color: root.panelBg; border.color: root.borderColor; radius: 6 }
                                    contentItem: ListView { clip: true; implicitHeight: contentHeight; model: algoCategoryFilterCombo.delegateModel }
                                }
                                delegate: ItemDelegate {
                                    width: algoCategoryFilterCombo.width - 6; height: 28
                                    contentItem: Text { text: modelData; color: root.textColor; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; leftPadding: 10 }
                                    background: Rectangle { color: hovered ? root.tableHoverBg : "transparent"; radius: 3 }
                                }
                                onActivated: root.applyAlgoCategoryFilter(currentText)
                            }

                            RowLayout {
                                anchors.horizontalCenter: parent.horizontalCenter
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 11
                                spacing: 16
                                Text {
                                    text: "总计 " + root.totalAlgoCount
                                    color: root.textColor; font.pixelSize: 13; font.bold: true
                                }
                                Rectangle { width: 1; height: 14; color: root.borderColor }
                                Rectangle {
                                    Layout.preferredWidth: Math.max(22, cleanStatText.implicitWidth + 10)
                                    Layout.preferredHeight: 18; radius: 9
                                    color: Qt.rgba(47/255, 133/255, 90/255, 0.15)
                                    Text { id: cleanStatText; anchors.centerIn: parent; text: "清 " + root.cleaningCount; color: root.cleanTagColor; font.pixelSize: 10; font.bold: true }
                                }
                                Rectangle {
                                    Layout.preferredWidth: Math.max(22, genStatText.implicitWidth + 10)
                                    Layout.preferredHeight: 18; radius: 9
                                    color: Qt.rgba(194/255, 125/255, 14/255, 0.15)
                                    Text { id: genStatText; anchors.centerIn: parent; text: "生 " + root.generationCount; color: root.genTagColor; font.pixelSize: 10; font.bold: true }
                                }
                                Rectangle {
                                    Layout.preferredWidth: Math.max(22, evalStatText.implicitWidth + 10)
                                    Layout.preferredHeight: 18; radius: 9
                                    color: Qt.rgba(29/255, 78/255, 216/255, 0.15)
                                    Text { id: evalStatText; anchors.centerIn: parent; text: "评 " + root.evaluationCount; color: root.devAccentColor; font.pixelSize: 10; font.bold: true }
                                }
                                Rectangle {
                                    Layout.preferredWidth: Math.max(22, trainStatText.implicitWidth + 10)
                                    Layout.preferredHeight: 18; radius: 9
                                    color: Qt.rgba(180/255, 83/255, 9/255, 0.15)
                                    Text { id: trainStatText; anchors.centerIn: parent; text: "训 " + root.trainingCount; color: root.genTagColor; font.pixelSize: 10; font.bold: true }
                                }
                            }
                        }

                            Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor }

                        // ===== 清洗算法 =====
                        Rectangle {
                            visible: root.showCategorySection("清洗算法")
                            Layout.fillWidth: true; height: 38
                            color: root.cleaningExpanded ? Qt.rgba(47/255, 133/255, 90/255, 0.04) : "transparent"
                            MouseArea {
                                anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: root.cleaningExpanded = !root.cleaningExpanded
                            }
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 8
                                Text {
                                    text: root.cleaningExpanded ? "▼" : "▶"
                                    color: root.cleanTagColor; font.pixelSize: 10; Layout.preferredWidth: 14
                                }
                                Text {
                                    text: "清洗算法"; color: root.textColor; font.pixelSize: 13; font.bold: true
                                }
                                Rectangle {
                                    Layout.preferredWidth: Math.max(22, s1cnt.implicitWidth + 10)
                                    Layout.preferredHeight: 18; radius: 9
                                    color: Qt.rgba(47/255, 133/255, 90/255, 0.15)
                                    Text { id: s1cnt; anchors.centerIn: parent; text: root.cleaningCount; color: root.cleanTagColor; font.pixelSize: 10; font.bold: true }
                                }
                            }
                        }
                        Column {
                            visible: root.showCategorySection("清洗算法") && root.cleaningExpanded
                            Layout.fillWidth: true
                            Repeater {
                                model: cleaningAlgoModel
                                delegate: algoItemDelegate
                            }
                        }
                        Rectangle { visible: root.showCategorySection("清洗算法"); Layout.fillWidth: true; height: 1; color: root.borderColor }

                        // ===== 生成算法 =====
                        Rectangle {
                            visible: root.showCategorySection("生成算法")
                            Layout.fillWidth: true; height: 38
                            color: root.generationExpanded ? Qt.rgba(194/255, 125/255, 14/255, 0.04) : "transparent"
                            MouseArea {
                                anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: root.generationExpanded = !root.generationExpanded
                            }
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 8
                                Text {
                                    text: root.generationExpanded ? "▼" : "▶"
                                    color: root.genTagColor; font.pixelSize: 10; Layout.preferredWidth: 14
                                }
                                Text {
                                    text: "生成算法"; color: root.textColor; font.pixelSize: 13; font.bold: true
                                }
                                Rectangle {
                                    Layout.preferredWidth: Math.max(22, s2cnt.implicitWidth + 10)
                                    Layout.preferredHeight: 18; radius: 9
                                    color: Qt.rgba(194/255, 125/255, 14/255, 0.15)
                                    Text { id: s2cnt; anchors.centerIn: parent; text: root.generationCount; color: root.genTagColor; font.pixelSize: 10; font.bold: true }
                                }
                            }
                        }
                        Column {
                            visible: root.showCategorySection("生成算法") && root.generationExpanded
                            Layout.fillWidth: true
                            Repeater {
                                model: generationAlgoModel
                                delegate: algoItemDelegate
                            }
                        }
                        Rectangle { visible: root.showCategorySection("生成算法"); Layout.fillWidth: true; height: 1; color: root.borderColor }

                        // ===== 评估算法 =====
                        Rectangle {
                            visible: root.showCategorySection("评估算法")
                            Layout.fillWidth: true; height: 38
                            color: root.evaluationExpanded ? Qt.rgba(29/255, 78/255, 216/255, 0.04) : "transparent"
                            MouseArea {
                                anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: root.evaluationExpanded = !root.evaluationExpanded
                            }
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 8
                                Text {
                                    text: root.evaluationExpanded ? "▼" : "▶"
                                    color: root.devAccentColor; font.pixelSize: 10; Layout.preferredWidth: 14
                                }
                                Text {
                                    text: "评估算法"; color: root.textColor; font.pixelSize: 13; font.bold: true
                                }
                                Rectangle {
                                    Layout.preferredWidth: Math.max(22, s3cnt.implicitWidth + 10)
                                    Layout.preferredHeight: 18; radius: 9
                                    color: Qt.rgba(29/255, 78/255, 216/255, 0.15)
                                    Text { id: s3cnt; anchors.centerIn: parent; text: root.evaluationCount; color: root.devAccentColor; font.pixelSize: 10; font.bold: true }
                                }
                            }
                        }
                        Column {
                            visible: root.showCategorySection("评估算法") && root.evaluationExpanded
                            Layout.fillWidth: true
                            Repeater {
                                model: evaluationAlgoModel
                                delegate: algoItemDelegate
                            }
                        }
                        Rectangle { visible: root.showCategorySection("评估算法"); Layout.fillWidth: true; height: 1; color: root.borderColor }

                        // ===== 训练算法 =====
                        Rectangle {
                            visible: root.showCategorySection("训练算法")
                            Layout.fillWidth: true; height: 38
                            color: root.trainingExpanded ? Qt.rgba(180/255, 83/255, 9/255, 0.04) : "transparent"
                            MouseArea {
                                anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                                onClicked: root.trainingExpanded = !root.trainingExpanded
                            }
                            RowLayout {
                                anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 8
                                Text {
                                    text: root.trainingExpanded ? "▼" : "▶"
                                    color: root.genTagColor; font.pixelSize: 10; Layout.preferredWidth: 14
                                }
                                Text {
                                    text: "训练算法"; color: root.textColor; font.pixelSize: 13; font.bold: true
                                }
                                Rectangle {
                                    Layout.preferredWidth: Math.max(22, s4cnt.implicitWidth + 10)
                                    Layout.preferredHeight: 18; radius: 9
                                    color: Qt.rgba(180/255, 83/255, 9/255, 0.15)
                                    Text { id: s4cnt; anchors.centerIn: parent; text: root.trainingCount; color: root.genTagColor; font.pixelSize: 10; font.bold: true }
                                }
                            }
                        }
                        Column {
                            visible: root.showCategorySection("训练算法") && root.trainingExpanded
                            Layout.fillWidth: true
                            Repeater {
                                model: trainingAlgoModel
                                delegate: algoItemDelegate
                            }
                        }
                    }
                }
            }

            // ---------------- 右侧 (Detail)：插件详情配置台 ----------------
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: root.panelBg
                border.color: root.borderColor
                border.width: 1
                radius: 8
                clip: true

                Text {
                    anchors.centerIn: parent
                    text: "请在左侧选择或注册新算法插件"
                    color: root.textMuted
                    font.pixelSize: 16
                    visible: root.selectedAlgoIndex === -1
                }

                // 详情面板主体
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 25
                    spacing: 20
                    visible: root.selectedAlgoIndex !== -1

                    // 1. 顶部 Header
                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            spacing: 8
                            Text {
                                text: root.selectedAlgoField("name")
                                color: root.textColor
                                font.pixelSize: 22
                                font.bold: true
                            }

                            Label {
                                id: tagCatText
                                text: root.selectedAlgoIndex !== -1 ? (root.selectedAlgoField("category") + " > " + root.selectedAlgoField("subCategory")) : ""
                                color: {
                                    var c = root.selectedAlgoField("category")
                                    if (c === "清洗算法") return root.cleanTagColor
                                    if (c === "生成算法") return root.genTagColor
                                    return root.devAccentColor
                                }
                                font.pixelSize: 11
                                font.bold: true
                                leftPadding: 8
                                rightPadding: 8
                                topPadding: 3
                                bottomPadding: 3

                                background: Rectangle {
                                    color: "transparent"
                                    border.color: tagCatText.color
                                    border.width: 1
                                    radius: 4
                                }
                            }
                        }

                        Item { Layout.fillWidth: true }

                        // 操作按钮组 (已修复 color 属性重复设置导致的报错问题)
                        RowLayout {
                            spacing: 10
                            Button {
                                text: "✏️ 调参修改"
                                Layout.preferredHeight: 32
                                background: Rectangle { border.color: root.borderColor; border.width: 1; radius: 4; color: parent.hovered ? root.tableHoverBg : "transparent" }
                                contentItem: Text { text: parent.text; color: root.textColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                onClicked: {
                                    if(root.selectedAlgoIndex === -1) return;
                                    var idx = root.selectedAlgoIndex;
                                    var modelData = algoListModel.get(idx);

                                    root.pendingEditIndex = idx;
                                    inputAlgoName.text = modelData.name;
                                    if (modelData.category === "清洗算法") inputCategory.currentIndex = 0
                                    else if (modelData.category === "生成算法") inputCategory.currentIndex = 1
                                    else if (modelData.category === "训练算法") inputCategory.currentIndex = 2
                                    else inputCategory.currentIndex = 3

                                    var catIdx = inputSubCategory.find(modelData.subCategory);
                                    if (catIdx !== -1) { inputSubCategory.currentIndex = catIdx; }
                                    else { inputSubCategory.editText = modelData.subCategory; }

                                    inputScriptPath.text = modelData.script;
                                    inputDesc.text = modelData.desc;

                                    editingParamsModel.clear();
                                    if (modelData.paramsJson && modelData.paramsJson !== "") {
                                        var pArr = JSON.parse(modelData.paramsJson);
                                        for(var i=0; i<pArr.length; i++) editingParamsModel.append(pArr[i]);
                                    }
                                    algoConfigPopup.open();
                                }
                            }
                            Button {
                                text: "🗑️ 卸载环境"
                                Layout.preferredHeight: 32
                                background: Rectangle { border.color: root.dangerColor; border.width: 1; radius: 4; color: parent.hovered ? "#33F53F3F" : "transparent" }
                                contentItem: Text { text: parent.text; color: root.dangerColor; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                onClicked: {
                                    if(root.selectedAlgoIndex !== -1) {
                                        root.pendingDeleteIndex = root.selectedAlgoIndex;
                                        deleteConfirmPopup.open();
                                    }
                                }
                            }
                        }
                    }

                    Rectangle { Layout.fillWidth: true; height: 1; color: root.borderColor }

                    // 2. 脚本映射展示
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: "脚本物理挂载路径 (Target Script)"; color: root.devAccentMuted; font.pixelSize: 12; font.family: "Courier"; font.bold: true }
                        Rectangle {
                            Layout.fillWidth: true; height: 46; color: Theme.control; border.color: root.borderColor; border.width: 1; radius: 6
                            Text {
                                text: root.selectedAlgoField("script")
                                color: root.textColor
                                font.family: "Courier"
                                font.pixelSize: 14
                                anchors.verticalCenter: parent.verticalCenter; anchors.left: parent.left; anchors.leftMargin: 15
                            }
                        }
                    }

                    // 3. 描述
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: "接口简述"; color: root.textMuted; font.pixelSize: 12; font.bold: true }
                        Text {
                            text: root.selectedAlgoField("desc")
                            color: root.textColor; font.pixelSize: 14; wrapMode: Text.WordWrap; Layout.fillWidth: true; lineHeight: 1.4
                        }
                    }

                    // 4. 算法使用说明
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text { text: "算法使用说明"; color: root.primaryColor; font.pixelSize: 13; font.bold: true }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 88
                            color: Theme.control
                            border.color: root.borderColor
                            border.width: 1
                            radius: 6
                            Text {
                                anchors.fill: parent
                                anchors.margins: 12
                                color: root.textMuted
                                font.pixelSize: 13
                                lineHeight: 1.3
                                wrapMode: Text.WordWrap
                                text: algorithmUsageText(root.selectedAlgoField("category"))
                            }
                        }
                        Text {
                            text: "完整文档: docs/ALGORITHM_USAGE_GUIDE.md"
                            color: root.textMuted
                            font.pixelSize: 12
                        }
                    }

                    // 4.5 关联评估算法（仅训练算法可见）
                    ColumnLayout {
                        Layout.fillWidth: true; spacing: 8
                        visible: root.selectedAlgoField("category") === "训练算法"
                        Text { text: "关联评估算法"; color: root.devAccentColor; font.pixelSize: 13; font.bold: true }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 10
                            ComboBox {
                                id: bindingEvalCombo
                                Layout.fillWidth: true; Layout.preferredHeight: 32
                                model: bindingEvalModel; textRole: "display"; valueRole: "key"
                                background: Rectangle { color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 4 }
                                contentItem: Text { text: bindingEvalCombo.currentText; color: root.textColor; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; leftPadding: 10 }
                                popup: Popup {
                                    y: bindingEvalCombo.height + 2; width: bindingEvalCombo.width; padding: 3
                                    background: Rectangle { color: root.panelBg; border.color: root.borderColor; radius: 6 }
                                    contentItem: ListView { clip: true; implicitHeight: contentHeight; model: bindingEvalCombo.delegateModel }
                                }
                                delegate: ItemDelegate {
                                    width: bindingEvalCombo.width - 6; height: 28
                                    contentItem: Text { text: model.display; color: root.textColor; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; leftPadding: 10 }
                                    background: Rectangle { color: hovered ? root.tableHoverBg : "transparent"; radius: 3 }
                                }
                            }
                            Button {
                                text: "保存绑定"; Layout.preferredHeight: 32
                                background: Rectangle { color: root.devAccentColor; radius: 4 }
                                contentItem: Text { text: parent.text; color: "white"; font.pixelSize: 12; font.bold: true; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                onClicked: {
                                    var result = backendService.saveAlgorithmBinding(root.selectedAlgoField("key"), bindingEvalCombo.currentValue || "")
                                    if (result && result.ok) {
                                        root.showToast("✅ 绑定已保存")
                                        var idx = root.selectedAlgoIndex
                                        if (idx >= 0) { algoListModel.setProperty(idx, "boundEvalKey", bindingEvalCombo.currentValue || ""); algoListModel.setProperty(idx, "boundEvalName", bindingEvalCombo.currentText || "") }
                                    } else root.showToast("⚠️ 绑定失败")
                                }
                            }
                        }
                    }

                    // 5. 解析并展示动态 JSON 参数
                    ColumnLayout {
                        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 8
                        Text { text: "动态反射参数快照 (Read-Only)"; color: root.devAccentColor; font.pixelSize: 12; font.family: "Courier"; font.bold: true }

                        Rectangle {
                            Layout.fillWidth: true; Layout.fillHeight: true; color: root.bgDark; border.color: root.borderColor; border.width: 1; radius: 6; clip: true

                            Flickable {
                                anchors.fill: parent; anchors.margins: 15; contentHeight: paramText.contentHeight; clip: true
                                Text {
                                    id: paramText
                                    color: root.textColor; font.family: "Courier"; font.pixelSize: 14; lineHeight: 1.5
                                    text: {
                                        var rawParams = root.selectedAlgoField("paramsJson")
                                        if(!rawParams) return "[]\n// 无环境参数传入";
                                        try {
                                            var arr = JSON.parse(rawParams);
                                            if(arr.length === 0) return "[]\n// 无环境参数传入";
                                            var str = "[\n";
                                            for(var i=0; i<arr.length; i++) {
                                                var p = arr[i];
                                                str += '  { name: "' + p.n + '", label: "' + (p.label || p.n) + '", type: ' + (p.type || "string");
                                                str += ', default: <font color="' + root.devAccentColor + '">' + (p.v !== undefined ? p.v : "") + '</font>';
                                                if (p.min) str += ", min: " + p.min;
                                                if (p.max) str += ", max: " + p.max;
                                                if (p.options) str += ", options: [" + p.options + "]";
                                                str += " }";
                                                if(i < arr.length - 1) str += ",";
                                                str += "\n";
                                            }
                                            str += "]";
                                            return str;
                                        } catch(e) { return "JSON Parse Error"; }
                                    }
                                    textFormat: Text.RichText
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}



